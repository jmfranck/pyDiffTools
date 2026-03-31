import argparse
import inspect


class CommandRegistrationError(Exception):
    """Exception raised when attempting to register a duplicate subcommand."""

# Registry that stores all subcommands made available to the CLI dispatcher.
_COMMAND_SPECS = {}


def register_command(
    help_text,
    description=None,
    help=None,
    filename_extensions=None,
):
    """Register a command handler for the CLI dispatcher."""

    def decorator(func):
        name = func.__name__.replace("_", "-")
        if name in _COMMAND_SPECS:
            raise CommandRegistrationError(
                f"Command '{name}' already registered"
            )
        signature = inspect.signature(func)
        parameters = [
            parameter
            for parameter in signature.parameters.values()
            if parameter.kind
            not in [
                inspect.Parameter.VAR_POSITIONAL,
                inspect.Parameter.VAR_KEYWORD,
            ]
        ]
        # {{{ normalize the extensions
        if filename_extensions is None:
            return {}
        completion_allowednames = {}
        for argument_name, extensions in filename_extensions.items():
            if isinstance(extensions, str):
                extensions = [extensions]
            completion_allowednames[argument_name] = []
            for extension in extensions:
                if not isinstance(extension, str) or len(extension.strip()) == 0:
                    raise CommandRegistrationError(
                        "filename_extensions must contain non-empty strings"
                    )
                extension = extension.strip()
                if extension.startswith("*."):
                    completion_allowednames[argument_name].append(extension)
                elif extension.startswith("."):
                    completion_allowednames[argument_name].append("*" + extension)
                else:
                    completion_allowednames[argument_name].append("*." + extension)
        # }}}
        unknown_arguments = sorted(
            set(completion_allowednames)
            - {parameter.name for parameter in parameters}
        )
        if unknown_arguments:
            raise CommandRegistrationError(
                "filename_extensions references unknown arguments: "
                + ", ".join(unknown_arguments)
            )
        _COMMAND_SPECS[name] = {
            "handler": func,
            "help": help_text.strip(),
            "description": (
                description if description is not None else help_text
            ).strip(),
            "arguments": [],
        }
        argument_help = help if help is not None else {}
        for parameter in parameters:
            flags = []
            kwargs = {}
            if parameter.default is inspect._empty:
                flags.append(parameter.name)
                if parameter.name == "arguments":
                    # Most commands accept a raw list of trailing arguments.
                    kwargs["nargs"] = argparse.REMAINDER
                    kwargs["help"] = argparse.SUPPRESS
            else:
                # Single-letter keywords use a short flag; everything else uses
                # the long two-dash style expected by the CLI.
                dash_prefix = "-" if len(parameter.name) == 1 else "--"
                flags.append(dash_prefix + parameter.name.replace("_", "-"))
                kwargs["default"] = parameter.default
                if isinstance(parameter.default, bool):
                    # Boolean flags toggle on or off without needing a value.
                    kwargs["action"] = (
                        "store_false" if parameter.default else "store_true"
                    )
                elif parameter.default is not None:
                    kwargs["type"] = type(parameter.default)
            if parameter.name in argument_help:
                kwargs["help"] = argument_help[parameter.name].strip()
            argument_spec = {"flags": flags, "kwargs": kwargs}
            if parameter.name in completion_allowednames:
                argument_spec["completion_allowednames"] = (
                    completion_allowednames[parameter.name]
                )
            _COMMAND_SPECS[name]["arguments"].append(argument_spec)
        return func

    return decorator
