"""
translators/base.py

Implements the Base Translator class
"""

# This shouldn't be a problem if we are targetting sub-3.6 python versions
# pylint: disable=consider-using-f-string
# pylint: disable=line-too-long

import enum
import typing
from multiprocessing.pool import ThreadPool

import bs4

from translatepy import models, utils, exceptions
from translatepy.language import Language

# Types
T = typing.TypeVar('T')  # The method given to the decorator
C = typing.TypeVar('C', bound="BaseTranslator")  # The expected result class for `models.Result`
R = typing.TypeVar('R')  # The expected result class for `LazyIterable`


class LazyIterable(typing.Generic[R]):
    """
    An object which can be iterated through, even multiple times, but lazy loads the results.
    """

    def __init__(self, func: typing.Callable[[str], R], texts: typing.Optional[typing.Iterable[str]] = None) -> None:
        self.func = func
        self.texts = texts or []
        self.results: typing.List[R] = []

    def __iter__(self):
        current = 0
        for text in self.texts:
            try:
                yield self.results[current]
            except IndexError:
                result = self.func(text)
                self.results.append(result)  # caches the result
                yield result
            current += 1

    def __getitem__(self, index: int):
        current = 0
        for element in self:
            if current >= index:
                return element
            current += 1
        raise IndexError("list index out of range")


class BaseTranslateException(exceptions.TranslatepyException):
    """
    A translator exception, indicating a problem which occured during translation
    """
    error_codes = {}

    def __init__(self, status_code: int = -1, message: typing.Optional[str] = None):
        """
        Parameters
        ----------
        status_code: int, default = -1
        message: typing.Optional[str], default = None
        """
        if message is None:
            unknown_status_code_msg = "Unknown error. Error code: {}".format(status_code)
            self.message = self.error_codes.get(status_code, unknown_status_code_msg)
        else:
            self.message = message

        self.status_code = status_code

        super().__init__(self.message)

    def __str__(self):
        """
        """
        return "{} | {}".format(self.status_code, self.message)


# TODO: ADD `HTML` AGAIN


class Flag(enum.Enum):
    """
    Defines a set of internal flags the handlers can send to the validator
    """
    MULTIPLE_RESULTS = "multi"


class BaseTranslator:
    """
    The core of translatepy

    This defines a "Translator" instance, which is the gateway between the translator logic and translatepy
    """

    _caches: typing.Dict[str, utils.lru_cacher.LRUDictCache] = {}
    _supported_languages: typing.Optional[typing.Set[Language]] = None

    def _validate_text(self, text: typing.Union[str, typing.Any]) -> typing.Optional[str]:
        """
        Validates the given text, enforcing its type

        Parameters
        ----------
        text: str
            The text to validate

        Returns
        -------
        str
            The text as a string
        """
        if not text:
            return None  # should not continue
        text = str(text)
        if utils.sanitize.remove_spaces(text) == "":
            return None  # should not continue
        return text

    def _language_to_code(self, language: Language) -> typing.Union[str, typing.Any]:
        """
        Translates the given `translatepy.Language` object into the translator's internally suitable language code

        Parameters
        ----------
        language: Language
            The language to translate

        Returns
        -------
        Any
            The language code to be used internally
        """
        return self._validate_language(language).alpha2

    def _code_to_language(self, code: typing.Union[str, typing.Any]) -> Language:
        """
        Translates the given language code to a `translatepy.Language` object

        Parameters
        ----------
        code: str
            The language code to translate

        Returns
        -------
        Language
            The `translatepy.Language` object
        """
        return Language(code)  # hoping for now that the codes used are standard

    def _validate_language(self, language: typing.Union[str, Language], *args, **kwargs) -> Language:
        """
        Validates the given language

        Parameters
        ----------
        language: str

        Returns
        -------
        str
        """
        language = Language(language, *args, **kwargs)

        if self._supported_languages:  # Check if the attribute is not empty
            if language not in self._supported_languages:
                raise exceptions.UnsupportedLanguage("The language {language_code} is not supported by {service}".format(language_code=language, service=self))

        return language

    @staticmethod
    def _validate_method(method: typing.Optional[T] = None) -> T:
        """
        Internal decorator to automatically validate the different methods

        Parameters
        ----------
        method: Callable, optional
            The method to validate. If omitted, the wrapper will assume that the function was decorated without parameters.
        """
        def wrap(func: typing.Callable):
            # print("Registering", func.__name__)

            @typing.overload
            def validation(self: C, text: str, *args, **kwargs) -> models.Result[C]: ...

            @typing.overload
            def validation(self: C, text: typing.Iterable[str], *args, **kwargs) -> LazyIterable[models.Result[C]]: ...

            def validation(self: C,
                           text: typing.Union[str, typing.Iterable[str]],
                           *args, **kwargs) -> typing.Union[models.Result[C],
                                                            LazyIterable[models.Result[C]]]:
                # print("Calling", func.__name__)

                def worker(text: str) -> models.Result[C]:
                    """
                    Inner worker which actually validates everything and calls the handlers.
                    """
                    valid_text = self._validate_text(text)

                    hash_source = [utils.hasher.hash_object(valid_text)]

                    generator = func(self, valid_text or "", *args, **kwargs)

                    result = None

                    multiple_results = False

                    for element in generator:
                        if isinstance(element, models.Result) or element is Flag.MULTIPLE_RESULTS:
                            if element is Flag.MULTIPLE_RESULTS:
                                result = []
                                multiple_results = True
                            else:
                                result = element

                            if valid_text is None:
                                return result  # should be the empty result, because `text` is "empty"
                            break
                        hash_source.append(utils.hasher.hash_object(element))

                    if result is None:
                        raise ValueError("No result returned by the translator")

                    cache_key = utils.hasher.hash_object(hash_source)
                    try:
                        result = self._caches[func.__name__][cache_key]
                    except Exception:
                        try:
                            result: typing.Union[models.Result, typing.Iterable[models.Result]] = next(generator)
                            # making sure those are set
                            if multiple_results:
                                for element in result:
                                    element.service = self
                                    element.source = valid_text
                            else:
                                result.service = self
                                result.source = valid_text
                        except StopIteration:
                            return result  # should still be the empty result

                        try:
                            self._caches[func.__name__][cache_key] = result
                        except KeyError:
                            self._caches[func.__name__] = utils.lru_cacher.LRUDictCache(maxsize=1024, **{cache_key: result})

                    return result

                try:
                    if not isinstance(text, str):
                        raise ValueError("Is iterable but a string")
                    _ = iter(text)  # should raise `TypeError` if not iterable
                    return LazyIterable(func=worker, texts=text)
                except (ValueError, TypeError):
                    return worker(text)

            validation.__doc__ = func.__doc__
            validation.__name__ = func.__name__

            return validation

        if method is None:
            return wrap  # Called with parentheses
        return wrap(method)  # Called without params

    # `translate`
    # Translates a given text into the desired language, herein `dest_lang`
    # Type overloads

    @typing.overload
    def translate(self: C, text: str, dest_lang: typing.Union[str, Language], source_lang: typing.Union[str, Language] = "auto") -> models.TranslationResult[C]:
        """
        Translates the given `text` into the given `dest_lang`

        Parameters
        ---------
        text: str
            The text to translate
        dest_lang: str | Language
            The language to translate to
        source_lang: str | Language, default = "auto"
            The language `text` is in. If "auto", the translator will try to infer the language from `text`

        Returns
        -------
        TranslationResult
            The result of the translation
        """

    @typing.overload
    def translate(self: C, text: typing.Iterable[str], dest_lang: typing.Union[str, Language], source_lang: typing.Union[str, Language] = "auto") -> LazyIterable[models.TranslationResult[C]]:
        """
        Translates all of the elements in `text` into the given `dest_lang`

        Note: aka "Bulk Translation"

        Parameters
        ---------
        text: Iterable[str]
            A list of texts you want to translate
        dest_lang: str | Language
            The language to translate to
        source_lang: str | Language, default = "auto"
            The language `text` is in. If "auto", the translator will try to infer the language from `text`

        Returns
        -------
        LazyIterable[TranslationResult]
            An iterable which holds the different translations
        """

    # Implementation

    @_validate_method
    def translate(self: C,
                  text: typing.Union[str, typing.Iterable[str]],
                  dest_lang: typing.Union[str, Language],
                  source_lang: typing.Union[str, Language] = "auto") -> typing.Union[models.TranslationResult[C],
                                                                                     LazyIterable[models.TranslationResult[C]]]:  # type: ignore | the decorator actually returns a `TranslationResult`
        """
        Translates `text` into the given `dest_lang`

        Note: Refer to the overloaded methods docstrings for more information.
        """

        # `text` is already valid

        dest_lang = self._validate_language(dest_lang)
        dest_lang_code = self._language_to_code(dest_lang)
        yield dest_lang_code  # send it to the hash builder

        source_lang = self._validate_language(source_lang)
        source_lang_code = self._language_to_code(source_lang)
        yield source_lang_code  # send it to the hash builder

        yield models.TranslationResult(
            service=self,
            source=text,
            source_lang=source_lang,
            dest_lang=dest_lang,
            translation=text
        )

        if dest_lang == source_lang:
            return  # will stop the translation here

        yield self._translate(text=text, dest_lang=dest_lang_code, source_lang=source_lang_code)

    def _translate(self: C, text: str, dest_lang: typing.Any, source_lang: typing.Any) -> models.TranslationResult[C]:
        """
        The internal handler which contains the translator specific logic to retrieve all of the information

        Parameters
        ---------
        text: str
            The text to translate
        dest_lang: Any
            The language code for the destination language, as returned by `_language_to_code`
        source_lang: Any
            The language code for the source text language, as returned by `_language_to_code`

        Returns
        -------
        TranslationResult
            The result of the translation, this can omit `service` and `source`
        """
        raise exceptions.UnsupportedMethod()

    # `alternatives`
    # Returns the different alternative translations available for a given previous translation.

    # Type overloads

    @typing.overload
    def alternatives(self: C, translation: models.TranslationResult[C]) -> typing.List[models.TranslationResult[C]]:
        """
        Returns the different alternative translations available for a given previous translation.

        Parameters
        ----------
        translation: TranslationResult
            The previous translation

        Returns
        -------
        list[TranslationResult]
            The list of other translations a word might have
        """

    @typing.overload
    def alternatives(self: C, translation: typing.Iterable[models.TranslationResult[C]]) -> LazyIterable[typing.List[models.TranslationResult[C]]]:
        """
        Returns the different alternative translations available for all of the given translations.

        Parameters
        ----------
        translation: Iterable[TranslationResult]
            All of the previous translation

        Returns
        -------
        LazyIterable[list[TranslationResult]]
            All of the other translations
        """
    # Implementation

    @_validate_method
    def alternatives(self: C, translation: models.TranslationResult) -> typing.Union[typing.List[models.TranslationResult[C]],
                                                                                     LazyIterable[typing.List[models.TranslationResult[C]]]]:  # type: ignore | the decorator actually returns a `list[TranslationResult]`
        """
        Returns the different alternative translations available for the given `translation`.

        Note: Refer to the overloaded methods docstrings for more information.
        """
        yield translation.source_lang
        yield translation.dest_lang
        yield translation.source
        yield Flag.MULTIPLE_RESULTS

        try:
            result = self._alternatives(translation=translation)
            if isinstance(result, models.TranslationResult):  # if returned a single translation
                return [result]
            return result
        except Exception:
            return []

    def _alternatives(self: C, translation: models.TranslationResult) -> typing.Union[models.TranslationResult[C],
                                                                                      typing.List[models.TranslationResult[C]]]:
        """
        Internal handler for the `alternative` method

        Refer to `alternative` for more information on what this does

        Note: The translator developer could make use of the `raw` parameter to avoid making more requests if they are already given in the first run.

        The developer can either return a list of alternatives or a single other translation.
        The developer shouldn't return the translation given by the end-user.

        Parameters
        ----------
        translation: TranslationResult
            The previous translation

        Returns
        -------
        list[TranslationResult]
            The list of other translations a word might have, this can omit `service` and `source`
        """
        raise exceptions.UnsupportedMethod()

    # `transliterate`
    # Returns the transliteration for a given text

    # Type overloads

    @typing.overload
    def transliterate(self: C, text: str, dest_lang: typing.Union[str, Language], source_lang: typing.Union[str, Language] = "auto") -> models.TransliterationResult[C]:
        """
        Transliterates the given `text` into the given `dest_lang`

        Parameters
        ---------
        text: str
            The text to transliterate
        dest_lang: str | Language
            The language to translate to
        source_lang: str | Language, default = "auto"
            The language `text` is in. If "auto", the translator will try to infer the language from `text`

        Returns
        -------
        TransliterationResult
            The result of the transliteration
        """

    @typing.overload
    def transliterate(self: C, text: typing.Iterable[str], dest_lang: typing.Union[str, Language], source_lang: typing.Union[str, Language] = "auto") -> LazyIterable[models.TransliterationResult[C]]:
        """
        Transliterates all of the given `text` to the given `dest_lang`

        Parameters
        ---------
        text: Iterable[str]
            The texts to transliterate
        dest_lang: str | Language
            The language to translate to
        source_lang: str | Language, default = "auto"
            The language `text` is in. If "auto", the translator will try to infer the language from `text`

        Returns
        -------
        LazyIterable[TransliterationResult]
            An iterable which contains the transliterations
        """
    # Implementation
    @_validate_method
    def transliterate(self: C,
                      text: typing.Union[str, typing.Iterable[str]],
                      dest_lang: typing.Union[str, Language],
                      source_lang: typing.Union[str, Language] = "auto") -> typing.Union[models.TransliterationResult[C],
                                                                                         LazyIterable[models.TransliterationResult[C]]]:  # type: ignore | the decorator actually returns a `TransliterationResult`
        """
        Transliterates the given `text` to the given `dest_lang`

        Note: Refer to the overloaded methods docstrings for more information.
        """
        # `text` is already valid

        dest_lang = self._validate_language(dest_lang)
        dest_lang_code = self._language_to_code(dest_lang)
        yield dest_lang_code  # send it to the hash builder

        source_lang = self._validate_language(source_lang)
        source_lang_code = self._language_to_code(source_lang)
        yield source_lang_code  # send it to the hash builder

        yield models.TransliterationResult(
            service=self,
            source=text,
            source_lang=source_lang,
            dest_lang=dest_lang,
            transliteration=text
        )

        if dest_lang == source_lang:
            return  # will stop the transliteration here

        yield self._transliterate(
            text=text,
            dest_lang=dest_lang_code,
            source_lang=source_lang_code
        )

    def _transliterate(self: C, text: str, dest_lang: typing.Any, source_lang: typing.Any) -> models.TransliterationResult[C]:
        """
        The internal handler which contains the translator specific logic to retrieve transliterations

        Parameters
        ---------
        text: str
            The text to transliterate
        dest_lang: Any
            The language code for the destination language, as returned by `_language_to_code`
        source_lang: Any
            The language code for the source text language, as returned by `_language_to_code`

        Returns
        -------
        TransliterationResult
            The transliteration result, this can omit `service` and `source`
        """
        raise exceptions.UnsupportedMethod()

    # `spellcheck`
    # Checks for spelling mistakes within a given text

    # Type overloads

    @typing.overload
    def spellcheck(self: C, text: str, source_lang: typing.Union[str, Language] = "auto") -> typing.Union[models.SpellcheckResult[C], models.RichSpellcheckResult[C]]:
        """
        Checks for spelling mistakes in the given `text`

        Parameters
        ---------
        text: str
            The text to check for spelling mistakes
        source_lang: str | Language, default = "auto"
            The language `text` is in. If "auto", the translator will try to infer the language from `text`

        Returns
        -------
        SpellcheckResult
            The result of the spell check
        RichSpellcheckResult
            If supported by the translator, rich spellchecking results, which include the different mistakes made
        """

    @typing.overload
    def spellcheck(self: C, text: typing.Iterable[str], source_lang: typing.Union[str, Language] = "auto") -> LazyIterable[typing.Union[models.SpellcheckResult[C], models.RichSpellcheckResult[C]]]:
        """
        Checks for spelling mistakes in all of the given `text`

        Parameters
        ---------
        text: Iterable[str]
            All of the texts to check for spelling mistakes
        source_lang: str | Language, default = "auto"
            The language `text` is in. If "auto", the translator will try to infer the language from `text`

        Returns
        -------
        LazyIterable[SpellcheckResult]
            The results of the spell checks
        LazyIterable[RichSpellcheckResult]
            If supported by the translator, rich spellchecking results, which include the different mistakes made
        """

    # Implementation
    @_validate_method
    def spellcheck(self: C,
                   text: typing.Union[str, typing.Iterable[str]],
                   source_lang: typing.Union[str, Language] = "auto") -> typing.Union[typing.Union[models.SpellcheckResult[C], models.RichSpellcheckResult[C]],
                                                                                      LazyIterable[typing.Union[models.SpellcheckResult[C], models.RichSpellcheckResult[C]]]]:  # type: ignore | the decorator actually returns a `SpellcheckResult`
        """
        Checks for spelling mistakes in the given `text`

        Note: Refer to the other overloaded methods for more information.
        """
        source_lang = self._validate_language(source_lang)
        source_lang_code = self._language_to_code(source_lang)
        yield source_lang_code  # send it to the hash builder

        yield models.SpellcheckResult(
            service=self,
            source=text,
            source_lang=source_lang,
            corrected=text
        )

        yield self._spellcheck(
            text=text,
            source_lang=source_lang_code
        )

    def _spellcheck(self: C, text: str, source_lang: typing.Any) -> typing.Union[models.SpellcheckResult[C], models.RichSpellcheckResult[C]]:
        """
        The internal handler which contains the translator specific logic to check for spelling mistakes

        Parameters
        ---------
        text: str
            The text to translate
        source_lang: Any
            The language code for the source text language, as returned by `_language_to_code`

        Returns
        -------
        SpellcheckResult
            The result of the spell checking, this can omit `service` and `source`
        RichSpellcheckResult
            If supported, providing more information for the spell checking, this can omit `service` and `source`
        """
        raise exceptions.UnsupportedMethod()

    # `language`
    # Detects the language of a given text

    # Type overloads

    @typing.overload
    def language(self: C, text: str) -> models.LanguageResult[C]:
        """
        Returns the detected language for the given `text`

        Parameters
        ---------
        text: str
            The text to get the language for

        Returns
        -------
        LanguageResult
            The result of the language detection
        """

    @typing.overload
    def language(self: C, text: typing.Iterable[str]) -> LazyIterable[models.LanguageResult[C]]:
        """
        Returns the detected language for all of the given `text`

        Parameters
        ---------
        text: Iterable[str]
            The texts to get the language of

        Returns
        -------
        LazyIterable[LanguageResult]
            The results of the language detections
        """

    # Implementation
    @_validate_method
    def language(self: C,
                 text: typing.Union[str, typing.Iterable[str]]) -> typing.Union[models.LanguageResult[C],
                                                                                LazyIterable[models.LanguageResult[C]]]:  # type: ignore | the decorator actually returns a `LanguageResult`
        """
        Returns the detected language for the given `text`

        Note: Refer to the other overloaded methods for more information.
        """
        # `text` is already valid

        yield models.LanguageResult(
            service=self,
            source=text,
            language=Language("auto")
        )

        yield self._language(text=text)

    def _language(self: C, text: str) -> models.LanguageResult[C]:
        """
        The internal handler which contains the translator specific logic to detect languages

        Parameters
        ----------
        text: str
            The text to get the language for

        Returns
        -------
        LanguageResult
            The language detection result, this can omit `service` and `source`
        """
        raise exceptions.UnsupportedMethod()

    # `example`
    # Returns an example use cas for a given text

    # Type overloads

    @typing.overload
    def example(self: C, text: str, source_lang: typing.Union[str, Language] = "auto") -> typing.List[models.ExampleResult[C]]:
        """
        Returns use cases for the given `text`

        Parameters
        ---------
        text: str
            The text to get the example for
        source_lang: str | Language
            The language `text` is in. If "auto", the translator will try to infer the language from `text`

        Returns
        -------
        list[ExampleResult]
            The examples
        """

    @typing.overload
    def example(self: C, text: typing.Iterable[str], source_lang: typing.Union[str, Language] = "auto") -> LazyIterable[typing.List[models.ExampleResult[C]]]:
        """
        Returns use cases for all of the given `text`

        Parameters
        ---------
        text: Iterable[str]
            The texts to get the examples for
        source_lang: str | Language
            The language `text` is in. If "auto", the translator will try to infer the language from `text`

        Returns
        -------
        LazyIterable[list[ExampleResult]]
            All of the examples
        """

    # Implementation
    @_validate_method
    def example(self: C,
                text: typing.Union[str, typing.Iterable[str]],
                source_lang: typing.Union[str, Language] = "auto") -> typing.Union[typing.List[models.ExampleResult[C]],
                                                                                   LazyIterable[typing.List[models.ExampleResult[C]]]]:  # type: ignore | the decorator actually returns a `ExampleResult`
        """
        Returns use cases for the given `text`

        Note: Refer to the other overloaded methods for more information.
        """
        # `text` is already valid
        source_lang = self._validate_language(source_lang)
        source_lang_code = self._language_to_code(source_lang)
        yield source_lang_code  # send it to the hash builder

        yield Flag.MULTIPLE_RESULTS

        try:
            result = self._example(text=text, source_lang=source_lang_code)
            if isinstance(result, models.ExampleResult):  # it returned a single example
                return [result]
            return result
        except Exception:
            return []

    def _example(self: C, text: str, source_lang: typing.Any) -> typing.Union[models.ExampleResult[C],
                                                                              typing.List[models.ExampleResult[C]]]:
        """
        The internal handler which contains the translator specific logic to retrieve examples

        Parameters
        ----------
        text: str
            The text to get the example for
        source_lang: Any
            The language code for the source text language, as returned by `_language_to_code`

        Returns
        -------
        ExampleResult
             A use case for `text`, this can omit `service` and `source`
        list[ExampleResult]
             Multiple use cases for `text`, this can omit `service` and `source`
        """
        raise exceptions.UnsupportedMethod()

    # `example`
    # Returns the meaning and multiple information on a given text

    # Type overloads

    @typing.overload
    def dictionary(self: C, text: str, source_lang: typing.Union[str, Language] = "auto") -> typing.List[typing.Union[models.DictionaryResult[C], models.RichDictionaryResult[C]]]:
        """
        Returns the meaning for the given `text`

        Parameters
        ---------
        text: str
            The text to get the meaning for
        source_lang: str | Language
            The language `text` is in. If "auto", the translator will try to infer the language from `text`

        Returns
        -------
        DictionaryResult
            The meaning of the given `text`
        RichDictionaryResult
            If supported, a value which contains much more information on `text`
        """

    @typing.overload
    def dictionary(self: C, text: typing.Iterable[str], source_lang: typing.Union[str, Language] = "auto") -> LazyIterable[typing.List[typing.Union[models.DictionaryResult[C], models.RichDictionaryResult[C]]]]:
        """
        Returns the meaning for all of the given `text`

        Parameters
        ---------
        text: Iterable[str]
            The texts to get the meanings for
        source_lang: str | Language
            The language `text` is in. If "auto", the translator will try to infer the language from `text`

        Returns
        -------
        LazyIterable[DictionaryResult]
            The meanings for all of the given `text`
        LazyIterable[RichDictionaryResult]
            If supported, a value which contains much more information on all of the `text`
        """

    # Implementation
    @_validate_method
    def dictionary(self: C,
                   text: typing.Union[str, typing.Iterable[str]],
                   source_lang: typing.Union[str, Language] = "auto") -> typing.Union[typing.List[typing.Union[models.DictionaryResult[C], models.RichDictionaryResult[C]]],
                                                                                      LazyIterable[typing.List[typing.Union[models.DictionaryResult[C], models.RichDictionaryResult[C]]]]]:  # type: ignore | the decorator actually returns a `DictionaryResult`
        """
        Returns the meaning for the given `text`

        Note: Refer to the other overloaded methods for more information.
        """
        # `text` is already valid
        source_lang = self._validate_language(source_lang)
        source_lang_code = self._language_to_code(source_lang)
        yield source_lang_code  # send it to the hash builder

        yield Flag.MULTIPLE_RESULTS

        try:
            result = self._dictionary(text=text, source_lang=source_lang_code)
            if isinstance(result, models.DictionaryResult):  # it returned a single definition
                return [result]
            return result
        except Exception:
            return []

    def _dictionary(self: C,
                    text: str,
                    source_lang: typing.Any) -> typing.Union[typing.Union[models.DictionaryResult[C], models.RichDictionaryResult[C]],
                                                             typing.List[typing.Union[models.DictionaryResult[C], models.RichDictionaryResult[C]]]]:
        """
        The internal handler which contains the translator specific logic to retrieve dictionary results

        Parameters
        ----------
        text: str
            The text to get the example for
        source_lang: Any
            The language code for the source text language, as returned by `_language_to_code`

        Returns
        -------
        DictionaryResult
            The meaning of the given `text`, this can omit `service` and `source`
        RichDictionaryResult
            If supported, a value which contains much more information on `text`, this can omit `service` and `source`
        """
        raise exceptions.UnsupportedMethod

    @typing.overload
    def text_to_speech(self: C, text: str, speed: typing.Union[int, models.Speed] = 100, gender: models.Gender = models.Gender.OTHER, source_lang: typing.Union[str, Language] = "auto") -> models.TextToSpechResult[C]:
        """
        Returns the speech version of the given `text`

        Parameters
        ---------
        text: str
            The text to get the speech for
        speed: int | Speed
            The speed percentage of the text to speech result, if supported
        gender: Gender
            The gender of the voice, if supported
        source_lang: str | Language
            The language `text` is in. If "auto", the translator will try to infer the language from `text`

        Returns
        -------
        TextToSpeechResult
            The text to speech result
        """

    @typing.overload
    def text_to_speech(self: C, text: typing.Iterable[str], speed: typing.Union[int, models.Speed] = 100, gender: models.Gender = models.Gender.OTHER, source_lang: typing.Union[str, Language] = "auto") -> LazyIterable[models.TextToSpechResult[C]]:
        """
        Returns the speech version for all of the given `text`

        Parameters
        ---------
        text: str
            The texts to get the speech versions for
        speed: int | Speed
            The speed percentage of the text to speech result, if supported
        gender: Gender
            The gender of the voice, if supported
        source_lang: str | Language
            The language `text` is in. If "auto", the translator will try to infer the language from `text`

        Returns
        -------
        LazyIterable[TextToSpeechResult]
            The text to speech results
        """

    @_validate_method
    def text_to_speech(self: C,
                       text: typing.Union[str, typing.Iterable[str]],
                       speed: typing.Union[int, models.Speed] = 100,
                       gender: models.Gender = models.Gender.OTHER,
                       source_lang: typing.Union[str, Language] = "auto") -> typing.Union[models.TextToSpechResult[C],
                                                                                          LazyIterable[models.TextToSpechResult[C]]]:  # type: ignore | the decorator actually returns a `TextToSpechResult`
        """
        Returns the speech version of the given `text`

        Note: Refer to the other overloaded methods for more information.
        """
        if isinstance(speed, models.Speed):
            valid_speed = speed.value
        else:
            valid_speed = speed
        yield valid_speed

        source_lang = self._validate_language(source_lang)
        source_lang_code = self._language_to_code(source_lang)
        yield source_lang_code  # send it to the hash builder

        yield models.TextToSpechResult(
            service=self,
            source=text,
            source_lang=source_lang,
            result=b"",
            speed=valid_speed,
            gender=gender
        )

        yield self._text_to_speech(text=text, speed=valid_speed, gender=gender, source_lang=source_lang_code)

    def _text_to_speech(self: C, text: str, speed: int, gender: models.Gender, source_lang: typing.Any) -> models.TextToSpechResult[C]:
        """
        The internal handler which contains the translator specific logic to retrieve text to speech results

        Parameters
        ----------
        text: str
            The text to get the speech for
        speed: int
            The speed percentage of the text to speech result
        gender: Gender
            The gender of the voice, can be `Gender.OTHER`
        source_lang: str | Language
            The language `text` is in. If "auto", the translator will try to infer the language from `text`

        Returns
        -------
        TextToSpeechResult
            The text to speech result, `service` and `source` can be omitted.
        """
        raise exceptions.UnsupportedMethod()

    def clean_cache(self) -> None:
        """
        Cleans caches

        Returns
        -------
        None
        """
        for cache in self._caches.values():
            cache.clear()

    def __str__(self) -> str:
        """
        String representation of a translator.

        Returns
        -------
        str
        """
        class_name = self.__class__.__name__
        class_name = class_name[:class_name.rfind("Translate")]
        return "UnknownTranslator" if class_name == "" else class_name

    def __repr__(self) -> str:
        """
        Returns
        -------
        str
        """
        return "Translator({translator})".format(translator=self.__str__())
