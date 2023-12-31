
# translatepy API Reference

Welcome to the translatepy API Reference.

## Globals

### Response Format

Globally, JSON responses should be formatted as follows (even when critical errors occur)

```json
{
    "success": true,
    "message": "We successfully did this!",
    "error": null,
    "data": {}
}
```

| Field        | Description                                      | Nullable         |
| ------------ | ------------------------------------------------ | ---------------- |
| `success`    | Wether the request was a success or not          | False            |
| `message`    | A message describing what happened               | True             |
| `error`      | The exception name if an error occured           | True             |
| `data`       | The extra data, information asked in the request | False            |

### Errors

Multiple Errors can occur, server side or request side.

Specific errors are documented in each endpoint but these are the general errors that can occur on any endpoint:

| Exception                   | Description                                                                                                     | Code  |
| --------------------------- | --------------------------------------------------------------------------------------------------------------- | ----- |
| `SERVER_ERROR`              | When an error occurs on translatepy while processing a request                                                       | 500   |
| `MISSING_CONTEXT`           | When you are trying to access something which is only available in a Nasse context, and you aren't in one       | 500   |
| `INTERNAL_SERVER_ERROR`     | When a critical error occurs on the system                                                                      | 500   |
| `METHOD_NOT_ALLOWED`        | When you made a request with the wrong method                                                                   | 405   |
| `CLIENT_ERROR`              | When something is missing or is wrong with the request                                                          | 400   |
| `MISSING_VALUE`             | When a value is missing from the request                                                                        | 400   |
| `MISSING_PARAM`             | When a parameter is missing from the request                                                                    | 400   |
| `MISSING_DYNAMIC`           | When a dynamic routing value is missing from the requested URL                                                  | 400   |
| `MISSING_HEADER`            | When a header is missing from the request                                                                       | 400   |
| `MISSING_COOKIE`            | When a cookie is missing from the request                                                                       | 400   |
| `AUTH_ERROR`                | When an error occured while authenticating the request                                                          | 403   |

### Authenticated Requests

When a user needs to be logged in, the "Authorization" header needs to be set to the login token provided when logging in.

Alternatively, the "translatepy_token" parameter and "__translatepy_token" cookie can be used but these won't be prioritized.

If the endpoint is flagged for a "verified only" login, the account won't be fetched from any database but the token will be checked.

### Debug Mode

On debug mode (`-d` or `--debug`), multiple information are passed in the `debug` section of the response and the `DEBUG` log level is selected on the server.

The 'debug' section is available on every type of error, except the ones issued by Flask such as `INTERNAL_SERVER_ERROR`, `METHOD_NOT_ALLOWED`, etc. (they need to do the bare minimum to not raise an exception and therefore breaking the server)

The "call_stack" attribute is enabled only when an error occurs or the `call_stack` parameter is passed with the request.

```json
{
    "success": true,
    "message": "We couldn't fullfil your request",
    "error": null,
    "data": {
        "username": "Animenosekai"
    },
    "debug": {
        "time": {
            "global": 0.036757,
            "verification": 0.033558,
            "authentication": 0.003031,
            "processing": 4.9e-05,
            "formatting": 0.0001
        },
        "ip": "127.0.0.1",
        "headers": {
            "Host": "api.translatepy.com",
            "Connection": "close",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "fr-fr",
            "Accept-Encoding": "gzip, deflate, br",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0.3 Safari/605.1.15"
        },
        "values": {},
        "domain": "api.translatepy.com",
        "logs": [
            "1636562693.036563｜[INFO] [nasse.receive.Receive.__call__] → Incoming GET request to /account/name from 127.0.0.1",
            "1636562693.070008｜[ERROR] [nasse.exceptions.base.MissingToken.__init__] An authentication token is missing from the request"
        ],
        "call_stack": [
            "pass the 'call_stack' parameter to get the call stack"
        ]
    }
}
```

## Index

- [Language](./sections/Language.md#language)
  - [Language Details](./sections/Language.md#language-details)
  - [Language Search](./sections/Language.md#language-search)
  - [Language Details (dynamic)](./sections/Language.md#language-details-dynamic)
- [Translation](./sections/Translation.md#translation)
  - [Translate](./sections/Translation.md#translate)
  - [Translation Stream](./sections/Translation.md#translation-stream)
  - [Translate HTML](./sections/Translation.md#translate-html)
  - [Transliterate](./sections/Translation.md#transliterate)
  - [Spellcheck](./sections/Translation.md#spellcheck)
  - [Language](./sections/Translation.md#language-1)
  - [Text to Speech](./sections/Translation.md#text-to-speech)
