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
            else:
                flags.append("--" + parameter.name.replace("_", "-"))
                kwargs["default"] = parameter.default
                if parameter.default is not None:
                    kwargs["type"] = type(parameter.default)
            if parameter.name in argument_help:
                kwargs["help"] = argument_help[parameter.name].strip()
            _COMMAND_SPECS[name]["arguments"].append(
                {"flags": flags, "kwargs": kwargs, "dest": parameter.name}
            )
        return func

    return decorator
