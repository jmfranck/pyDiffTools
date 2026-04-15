import argparse
import logging

# Set up the command-line argument parser
parser = argparse.ArgumentParser(
    description="A script with configurable logging level."
)
parser.add_argument(
    "--log",
    default="WARNING",
    help="Set the logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)",
)
parsed_args, args = parser.parse_known_args()

# Set the logging level based on the command-line argument
numeric_level = getattr(logging, parsed_args.log.upper(), None)
if not isinstance(numeric_level, int):
    raise ValueError(f"Invalid log level: {parsed_args.log}")

logging.basicConfig(level=numeric_level)

# Example usage
logging.debug("This is a debug message")
logging.info("This is an info message")
logging.warning("This is a warning message")
logging.error("This is an error message")
logging.critical("This is a critical message")
print("and other parsed_args are", args)
