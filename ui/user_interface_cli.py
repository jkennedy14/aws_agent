from typing import Dict, Union
import logging

logger = logging.getLogger("aws_agent_logger")


class UserInterface:
    @staticmethod
    def prompt_user_for_ec2_requirements():
        """
        Hypothetically with full data source, would include other EC2 vars such as # GPUs
        For now, using found spreadsheet as SQL db - code extensible to more thorough data sources

        Could ask for each var as input separately
        Doing them together here keeps the same user response / bot response cadence
        and shows ability of LLM to differentiate function calling parameters

        Returns:
            str: The user response
        """

        prompt_to_user = "Enter EC2 requirements - Amount of RAM and CPU cores: "
        logger.info(f"Agent prompting user - {prompt_to_user}")

        return input(prompt_to_user)

    def display_recommended_config(
            self, config: Dict[str, Union[str, int]], config_type: str = "EC2"
    ):
        """
        Displaying recommended config to user. This function could be extended to generalized bot response

        Args:
            config (Dict[str, Union[str, int]]): The recommended ec2 or autoscaling config
            config_type (str, optional): The type of config. Defaults to "EC2". Options in current setup are "EC2" and "AutoScaling"

        Returns:
            None
        """

        self.log_to_user(f"\nRecommended optimized {config_type} config:")

        # for param, value in config.items():
        # self.log_to_user(f"{param}: {value}")

        config_string = "\n".join(
            f"{param}: {value}" for param, value in config.items()
        )

        self.log_to_user(config_string)

    @staticmethod
    def get_user_response():
        """
        Getting query from user - used to allow user to chat interactively

        Returns:
            str: The user response
        """

        user_query = input("User: ")
        logger.info(f"User: {user_query}")

        return user_query

    @staticmethod
    def log_to_user(text: str):
        """
        Logging to user

        Args:
            text (str): The text to be logged to the user

        Returns:
            None
        """

        logger.info("Agent: " + text)

        # simple logging for example
        print(text)
