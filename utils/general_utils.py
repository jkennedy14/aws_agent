from typing import Callable, Dict, Any
import logging
from logging.handlers import RotatingFileHandler


def setup_logger(logger_name: str = "aws_agent_logger") -> logging.Logger:
    """
    Creates basic backend logger that logs to a local file.

    Args:
        logger_name (str): The name of the logger to be created.

    Returns:
        logging.Logger: The created logger.
    """

    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.DEBUG)

    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    log_file = "app.log"
    file_handler = RotatingFileHandler(log_file, maxBytes=1024 * 1024, backupCount=5)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger


def call_function(function_data: Dict[str, Any]) -> Any:
    """
    Currently unused - all intents currently feeding kwargs directly into associated functions.

    This function calls a function with the provided keyword arguments.
    Note: Within the scope of this project, we are validating the function name and kwargs parsing in
    convert_raven_function_calling_response_to_function_name_and_args() within ../llm_interface.py
    Making the function name as str checking below not necessary but included for function completeness.

    Similarly, if the function is not defined in the global scope, the agent will validate the function call
    before this function is called - making global scope checking also unnecessary here but included to complete the utility.


    Parameters:
        function_data (Dict[str, Any]): A dictionary containing the function name and its keyword arguments.

    Returns:
        Any: The result of the function call.

    Raises:
        ValueError: If the function name is not a string.
        ValueError: If the function does not exist in the global scope.
    """

    function_name = function_data.get("function_name")
    kwargs = function_data.get("kwargs", {})

    if not isinstance(function_name, str):
        raise ValueError("Function name must be a string.")

    # get the function by name. Here we assume functions are defined in the global scope.
    func: Callable = globals().get(function_name)

    # if the function does not exist, raise an error
    if func is None:
        raise ValueError(f"Function '{function_name}' not found.")

    return func(**kwargs)
