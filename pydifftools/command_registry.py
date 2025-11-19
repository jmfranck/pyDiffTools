import argparse
import inspect


class CommandRegistrationError(Exception):
    """Exception raised when attempting to register a duplicate subcommand."""

# Registry that stores all subcommands made available to the CLI dispatcher.
_COMMAND_SPECS = {}


def register_command(help_text, description=None, help=None):
    """Register a command handler for the CLI dispatcher."""

    def decorator(func):
        name = func.__name__.replace("_", "-")
        if name in _COMMAND_SPECS:
            raise CommandRegistrationError(
                f"Command '{name}' already registered"
            )
        _COMMAND_SPECS[name] = {
            "handler": func,
            "help": help_text.strip(),
            "description": (
                description if description is not None else help_text
            ).strip(),
            "arguments": [],
        }
        signature = inspect.signature(func)
        argument_help = help if help is not None else {}
        for parameter in signature.parameters.values():
            if parameter.kind in [
                inspect.Parameter.VAR_POSITIONAL,
                inspect.Parameter.VAR_KEYWORD,
            ]:
                continue
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
            _COMMAND_SPECS[name]["arguments"].append(
                {"flags": flags, "kwargs": kwargs}
            )
        return func

    return decorator
