import json
from threading import Thread
from typing import List
from bs4 import NavigableString
from nasse import Response
from flask import Response as FlaskResponse
from nasse.models import Endpoint, Error, Login, Param, Return
from translatepy import Translator
from translatepy.exceptions import NoResult, UnknownLanguage, UnknownTranslator
from translatepy.language import Language
from translatepy.server.server import app
from collections import Counter

from translatepy.utils.queue import Queue

base = Endpoint(
    section="Translation",
    errors=[
        Error("TRANSLATEPY_EXCEPTION", "Generic exception raised when an error occured on translatepy. This is the base class for the other exceptions raised by translatepy."),
        Error("NO_RESULT", "When no result is returned from the translator(s)"),
        Error("PARAMETER_ERROR", "When a parameter is missing or invalid"),
        Error("PARAMETER_TYPE_ERROR", "When a parameter is of the wrong type"),
        Error("PARAMETER_VALUE_ERROR", "When a parameter is of the wrong value"),
        Error("TRANSLATION_ERROR", "When a translation error occurs"),
        Error("UNKNOWN_LANGUAGE", "When one of the provided language could not be understood by translatepy. Extra information like the string similarity and the most similar string are provided in `data`.", code=400),
        Error("UNKNOWN_TRANSLATOR", "When one of the provided translator/service could not be understood by translatepy. Extra information like the string similarity and the most similar string are provided in `data`.", code=400)
    ],
    login=Login(no_login=True)
)


def TranslatorList(value: str):
    return value.split(",")
    # return get_translator(value.split(","))


t = Translator()


@app.route("/translate", Endpoint(
    endpoint=base,
    name="Translate",
    description=t.translate.__doc__,
    params=[
        Param("text", "The text to translate"),
        Param("dest", "The destination language"),
        Param("source", "The source language", required=False),
        Param("translators", "The translator(s) to use. When providing multiple translators, the names should be comma-separated.", required=False, type=TranslatorList),
    ],
    returning=[
        Return("service", "Google", "The translator used"),
        Return("source", "Hello world", "The source text"),
        Return("sourceLang", "English", "The source language"),
        Return("destLang", "Japanese", "The destination language"),
        Return("result", "こんにちは世界", "The translated text")
    ]
))
def translate(text: str, dest: str, source: str = "auto", translators: List[str] = None):
    current_translator = t
    if translators is not None:
        try:
            current_translator = Translator(translators)
        except UnknownTranslator as err:
            return Response(
                data={
                    "guessed": str(err.guessed_translator),
                    "similarity": err.similarity,
                },
                message="translatepy could not find the given translator",
                error="UNKNOWN_TRANSLATOR",
                code=400
            )

    try:
        result = current_translator.translate(text=text, destination_language=dest, source_language=source)
    except UnknownLanguage as err:
        return Response(
            data={
                "guessed": str(err.guessed_language),
                "similarity": err.similarity,
            },
            message=str(err),
            error="UNKNOWN_LANGUAGE",
            code=400
        )
    return 200, {
        "service": str(result.service),
        "source": result.source,
        "sourceLang": result.source_language,
        "destLang": result.destination_language,
        "result": result.result
    }


@app.route("/stream", Endpoint(
    endpoint=base,
    name="Translation Stream",
    description=t.translate.__doc__ + " This endpoint returns a stream of results.",
    params=[
        Param("text", "The text to translate"),
        Param("dest", "The destination language"),
        Param("source", "The source language", required=False),
        Param("translators", "The translator(s) to use. When providing multiple translators, the names should be comma-separated.", required=False, type=TranslatorList),
    ],
    returning=[
        Return("service", "Google", "The translator used"),
        Return("source", "Hello world", "The source text"),
        Return("sourceLang", "English", "The source language"),
        Return("destLang", "Japanese", "The destination language"),
        Return("result", "こんにちは世界", "The translated text")
    ]
))
def translate(text: str, dest: str, source: str = "auto", translators: List[str] = None):
    current_translator = t
    if translators is not None:
        try:
            current_translator = Translator(translators)
        except UnknownTranslator as err:
            return Response(
                data={
                    "guessed": str(err.guessed_translator),
                    "similarity": err.similarity,
                },
                message="translatepy could not find the given translator",
                error="UNKNOWN_TRANSLATOR",
                code=400
            )

    try:
        dest = Language(dest)
        source = Language(source)
        # result = current_translator.translate(text=text, destination_language=dest, source_language=source)
    except UnknownLanguage as err:
        return Response(
            data={
                "guessed": str(err.guessed_language),
                "similarity": err.similarity,
            },
            message=str(err),
            error="UNKNOWN_LANGUAGE",
            code=400
        )

    def _translate(translator):
        result = translator.translate(
            text=text, destination_language=dest, source_language=source
        )
        if result is None:
            raise NoResult("{service} did not return any value".format(service=translator.__repr__()))
        return result

    def _fast_translate(queue: Queue, translator, index: int):
        try:
            translator = current_translator._instantiate_translator(translator, current_translator.services, index)
            result = _translate(translator)
            queue.put({
                "success": True,
                "error": None,
                "message": None,
                "data": {
                    "service": str(result.service),
                    "source": str(result.source),
                    "sourceLang": str(result.source_language),
                    "destLang": str(result.destination_language),
                    "result": str(result.result)
                }
            })
        except Exception as err:
            queue.put({
                "success": False,
                "error": str(err.__class__.__name__),
                "message": "; ".join(err.args),
                "data": {
                    "service": str(translator),
                }
            })

    _queue = Queue()
    threads = []
    for index, service in enumerate(current_translator.services):
        thread = Thread(target=_fast_translate, args=(_queue, service, index))
        thread.start()
        threads.append(thread)

    def handler():
        while True:
            try:
                result = _queue.get(threads=threads)  # wait for a value and return it
            except ValueError:
                break
            if result is None:
                break

            yield "data: {result}\n\n".format(result=json.dumps(result, ensure_ascii=False))

    return FlaskResponse(handler(), mimetype="text/event-stream")


@app.route("/html", Endpoint(
    endpoint=base,
    name="Translate HTML",
    description=t.translate_html.__doc__,
    params=[
        Param("code", "The HTML snippet to translate"),
        Param("dest", "The destination language"),
        Param("source", "The source language", required=False),
        Param("parser", "The HTML parser to use", required=False),
        Param("translators", "The translator(s) to use. When providing multiple translators, the names should be comma-separated.", required=False, type=TranslatorList),
    ],
    returning=[
        Return("services", ["Google", "Bing"], "The translators used"),
        Return("source", "<div><p>Hello, how are you today</p><p>Comment allez-vous</p></div>", "The source text"),
        Return("sourceLang", ["fra", "eng"], "The source languages"),
        Return("destLang", "Japanese", "The destination language"),
        Return("result", "<div><p>こんにちは、今日はお元気ですか</p><p>大丈夫</p></div>", "The translated text")
    ]
))
def translate(code: str, dest: str, source: str = "auto", parser: str = "html.parser", translators: List[str] = None):
    current_translator = t
    if translators is not None:
        try:
            current_translator = Translator(translators)
        except UnknownTranslator as err:
            return Response(
                data={
                    "guessed": str(err.guessed_translator),
                    "similarity": err.similarity,
                },
                message="translatepy could not find the given translator",
                error="UNKNOWN_TRANSLATOR",
                code=400
            )

    try:
        dest = Language(dest)
        source = Language(source)
    except UnknownLanguage as err:
        return Response(
            data={
                "guessed": str(err.guessed_language),
                "similarity": err.similarity,
            },
            message=str(err),
            error="UNKNOWN_LANGUAGE",
            code=400
        )
    services = []
    languages = []

    def _translate(node: NavigableString):
        try:
            result = current_translator.translate(str(node), destination_language=dest, source_language=source)
            services.append(str(result.service))
            languages.append(str(result.source_language))
            node.replace_with(result.result)
        except Exception:  # ignore if it couldn't find any result or an error occured
            pass

    result = current_translator.translate_html(html=code, destination_language=dest, source_language=source, parser=parser, __internal_replacement_function__=_translate)

    return 200, {
        "services": [element for element, _ in Counter(services).most_common()],
        "source": code,
        "sourceLang": [element for element, _ in Counter(languages).most_common()],
        "destLang": dest,
        "result": result
    }


@app.route("/transliterate", Endpoint(
    endpoint=base,
    name="Transliterate",
    description=t.transliterate.__doc__,
    params=[
        Param("text", "The text to transliterate"),
        Param("dest", "The destination language", required=False),
        Param("source", "The source language", required=False),
        Param("translators", "The translator(s) to use. When providing multiple translators, the names should be comma-separated.", required=False, type=TranslatorList),
    ],
    returning=[
        Return("service", "Google", "The translator used"),
        Return("source", "おはよう", "The source text"),
        Return("sourceLang", "Japanese", "The source language"),
        Return("destLang", "English", "The destination language"),
        Return("result", "Ohayou", "The transliteration")
    ]
))
def transliterate(text: str, dest: str = "English", source: str = "auto", translators: List[str] = None):
    current_translator = t
    if translators is not None:
        try:
            current_translator = Translator(translators)
        except UnknownTranslator as err:
            return Response(
                data={
                    "guessed": str(err.guessed_translator),
                    "similarity": err.similarity,
                },
                message="translatepy could not find the given translator",
                error="UNKNOWN_TRANSLATOR",
                code=400
            )

    try:
        result = current_translator.transliterate(text=text, destination_language=dest, source_language=source)
    except UnknownLanguage as err:
        return Response(
            data={
                "guessed": str(err.guessed_language),
                "similarity": err.similarity,
            },
            message=str(err),
            error="UNKNOWN_LANGUAGE",
            code=400
        )
    return 200, {
        "service": str(result.service),
        "source": result.source,
        "sourceLang": result.source_language,
        "destLang": result.destination_language,
        "result": result.result
    }


@app.route("/spellcheck", Endpoint(
    endpoint=base,
    name="Spellcheck",
    description=t.spellcheck.__doc__,
    params=[
        Param("text", "The text to spellcheck"),
        Param("source", "The source language", required=False),
        Param("translators", "The translator(s) to use. When providing multiple translators, the names should be comma-separated.", required=False, type=TranslatorList),
    ],
    returning=[
        Return("service", "Google", "The translator used"),
        Return("source", "God morning", "The source text"),
        Return("sourceLang", "English", "The source language"),
        Return("result", "Good morning", "The spellchecked text")
    ]
))
def spellcheck(text: str, source: str = "auto", translators: List[str] = None):
    current_translator = t
    if translators is not None:
        try:
            current_translator = Translator(translators)
        except UnknownTranslator as err:
            return Response(
                data={
                    "guessed": str(err.guessed_translator),
                    "similarity": err.similarity,
                },
                message="translatepy could not find the given translator",
                error="UNKNOWN_TRANSLATOR",
                code=400
            )

    try:
        result = current_translator.spellcheck(text=text, source_language=source)
    except UnknownLanguage as err:
        return Response(
            data={
                "guessed": str(err.guessed_language),
                "similarity": err.similarity,
            },
            message=str(err),
            error="UNKNOWN_LANGUAGE",
            code=400
        )
    return 200, {
        "service": str(result.service),
        "source": result.source,
        "sourceLang": result.source_language,
        "result": result.result
    }


@app.route("/language", Endpoint(
    endpoint=base,
    name="Language",
    description=t.language.__doc__,
    params=[
        Param("text", "The text to get the language of"),
        Param("translators", "The translator(s) to use. When providing multiple translators, the names should be comma-separated.", required=False, type=TranslatorList),
    ],
    returning=[
        Return("service", "Google", "The translator used"),
        Return("source", "Hello world", "The source text"),
        Return("result", "jpa", "The resulting language alpha-3 code")
    ]
))
def language(text: str, translators: List[str] = None):
    current_translator = t
    if translators is not None:
        try:
            current_translator = Translator(translators)
        except UnknownTranslator as err:
            return Response(
                data={
                    "guessed": str(err.guessed_translator),
                    "similarity": err.similarity,
                },
                message="translatepy could not find the given translator",
                error="UNKNOWN_TRANSLATOR",
                code=400
            )

    result = current_translator.language(text=text)

    return 200, {
        "service": str(result.service),
        "source": result.source,
        "result": result.result
    }


@app.route("/tts", Endpoint(
    endpoint=base,
    name="Text to Speech",
    description=t.text_to_speech.__doc__,
    params=[
        Param("text", "The text to convert to speech"),
        Param("source", "The source language", required=False),
        Param("speed", "The speed of the speech", required=False, type=int),
        Param("gender", "The gender of the speech", required=False),
        Param("translators", "The translator(s) to use. When providing multiple translators, the names should be comma-separated.", required=False, type=TranslatorList),
    ],
    returning=[
        Return("service", "Google", "The translator used"),
        Return("source", "Hello world", "The source text"),
        Return("sourceLang", "English", "The source language"),
        Return("destLang", "Japanese", "The destination language"),
        Return("result", "こんにちは世界", "The translated text")
    ]
))
def tts(text: str, speed: int = 100, gender: str = "female", source: str = "auto", translators: List[str] = None):
    current_translator = t
    if translators is not None:
        try:
            current_translator = Translator(translators)
        except UnknownTranslator as err:
            return Response(
                data={
                    "guessed": str(err.guessed_translator),
                    "similarity": err.similarity,
                },
                message="translatepy could not find the given translator",
                error="UNKNOWN_TRANSLATOR",
                code=400
            )

    result = current_translator.text_to_speech(text=text, speed=speed, gender=gender, source_language=source)

    return Response(result.result, content_type="audio/mpeg")
