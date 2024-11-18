from ui.user_interface_cli import UserInterface
from aws.aws_cli import EC2CLI, AutoScalingConfig, EC2InstanceConfig
from llm.llm_interface import LLMInterface
from utils.sql_utils import (
    create_sql_db_from_csv,
    SQLiteConnectionPool,
    find_best_instance,
)
from utils.general_utils import setup_logger
import config
from moto import mock_aws
from typing import Dict

logger = setup_logger()


class AWSAgent:
    """
    AWS Agent Class

    Args:
        ui (UserInterface): User interface object - handles responses logged to user
        ec2_cli (EC2CLI): EC2 CLI object - handles AWS CLI operations
        llm_interface (LLMInterface): LLM Interface object - handles LLM calls
        run_reflection (bool): Whether to run reflection on generated responses
    """

    def __init__(self, ui, ec2_cli, llm_interface, run_reflection=False):
        self.ui = ui
        self.ec2_cli = ec2_cli
        self.llm_interface = llm_interface
        self.run_reflection = run_reflection

        # starting config - contains default parameters for EC2
        # these can later be modified by user
        # Could also be moved to aws cli class when extended to other deployment types
        self.ec2_config = EC2InstanceConfig()
        self.as_config = AutoScalingConfig()
        self.as_config.VPCZoneIdentifier = ec2_cli.subnet_id
        self.autoscaling_enabled = False

        # memory - simple implementation
        self.conversation_history = []

    def handle_user_intent(self, predicted_function_call: Dict):
        """
        Note: Nexus LLM defaults to entire function call - func(*args, **kwargs) as return string
        Helper function used to read this into dictionary with function name and kwargs arguments
        Most function-calling architectures provide granularity by default - providing the function call and parameters
        separately.

        Here, we're directing to the appropriate function based on the function call for easier visualization of routing.
        If the number of intents were to scale significantly, this could easily be adjusted to directly call the function
        instead of having all if/else statements here. Would still need if/else for out of scope intent.

        Args:
            predicted_function_call (Dict): A dictionary containing the function name and its keyword arguments.
        """

        function_name = predicted_function_call["function_name"]
        kwargs = predicted_function_call["kwargs"]

        logger.info(f"{function_name} called with arguments {kwargs}")

        if function_name == "user_intent_ec2_type_selection":
            self.handle_user_intent_ec2_type_selection(**kwargs)

        elif function_name == "user_intent_confirm":
            self.handle_user_intent_confirm()

        elif function_name == "user_intent_enable_autoscaling":
            self.handle_user_intent_enable_autoscaling()

        elif function_name == "user_intent_display_current_deployment_config":
            # Function is used both as an intent and as a utility for other intents
            self.display_current_deployment_config()

        elif function_name == "user_intent_modify_ec2_config":
            self.handle_user_intent_modify_ec2_config(**kwargs)

        elif function_name == "user_intent_modify_as_config":
            self.handle_user_intent_modify_as_config(**kwargs)

        else:
            # out of scope - either out_of_scope function predicted directly, or generated text not one of above functions
            self.ui.log_to_user("Sorry, I didn't understand that. Please try again.")

    def handle_user_intent_enable_autoscaling(self):
        """
        Handle user intent to enable autoscaling
        """

        self.autoscaling_enabled = True
        self.display_current_deployment_config()

    def handle_user_intent_ec2_type_selection(self, **kwargs):
        """
        Handle user intent to select EC2 instance type based on input CPU and RAM requirements (also handles only one given)
        Keyword arguments are passed directly to the find_best_instance function
        """
        recommended_ec2_instance_spec = find_best_instance(**kwargs)

        if recommended_ec2_instance_spec["found"]:
            recommended_ec2_name = recommended_ec2_instance_spec["API_Name"]
            self.ec2_config.modify_config(InstanceType=recommended_ec2_name)
            self.display_current_deployment_config()
        else:
            # couldn't find suitable EC2 instance based on user requirements - goes into open dialogue flow
            # where user can specify new requirements
            self.ui.log_to_user(recommended_ec2_instance_spec["message"])

    def handle_user_intent_confirm(self):
        """
        Handle user intent to confirm deployment.
        Deploys final AWS CLI config
        """

        self.ec2_cli.deploy(
            self.ec2_config,
            self.as_config,
            autoscaling_enabled=self.autoscaling_enabled,
        )

    def handle_user_intent_modify_ec2_config(self, **kwargs):
        """
        Handles user intent to modify EC2 config.
        """

        self.ec2_config.modify_config(self.ui.log_to_user, **kwargs)
        self.display_current_deployment_config()

    def handle_user_intent_modify_as_config(self, **kwargs):
        """
        Handles user intent to modify autoscaling config (assuming autoscaling previously enabled)

        In this example, handling ec2 config and as config separately
        No reason why config couldn't be combined and handled in one call
        One advantage here in handling separately is we don't show user configs not relevant to him/her
        Handling combined would just require only showing config to user of what was changed
        """

        self.as_config.modify_config(self.ui.log_to_user, **kwargs)
        self.display_current_deployment_config()

    def display_current_deployment_config(self):
        """
        Deploys current EC2 and autoscaling config states to user.
        Used to handle the user intent to display current config in addition to being used as utility function for other intents
        """

        self.ui.display_recommended_config(self.ec2_config.to_dict(), config_type="EC2")

        if self.autoscaling_enabled:
            self.ui.display_recommended_config(
                self.as_config.to_dict(), config_type="AutoScaling"
            )

        self.ui.log_to_user("\nHow does this look?")

    def run(self):
        try:
            # intro sequence start - prompt user for ec2 type cpu and ram requirements
            ec2_requirements = self.ui.prompt_user_for_ec2_requirements()
            self.conversation_history.append(f"<human> {ec2_requirements} <human_end>")

            # hit LLM to get function call with predicted parameters
            predicted_function_call = (
                self.llm_interface.get_llm_function_calling_response(
                    ec2_requirements, self.conversation_history
                )
            )

            self.conversation_history.append(
                f"<bot> {predicted_function_call} <bot_end>"
            )

            # run reflection on current generation to adjust function call if needed
            if self.run_reflection:
                predicted_function_call = self.llm_interface.reflect(
                    ec2_requirements, self.conversation_history
                )

            self.handle_user_intent(predicted_function_call)

            # now go into dialogue flow
            while True:
                user_response = self.ui.get_user_response()
                self.conversation_history.append(f"<human> {user_response} <human_end>")
                agent_response = self.llm_interface.get_llm_function_calling_response(
                    user_response, self.conversation_history
                )

                if self.run_reflection:
                    agent_response = self.llm_interface.reflect(
                        user_response, self.conversation_history
                    )

                self.conversation_history.append(f"<bot> {agent_response} <bot_end>")

                self.handle_user_intent(agent_response)

        except Exception as e:
            self.ui.log_to_user(f"Error: {str(e)}")


def main():
    # setup mock local sql db from local csv
    create_sql_db_from_csv(
        "data/ec2_comp_edited.csv", db_path="ec2.db", table_name="ec2_rec"
    )

    config.sql_ec2_connection_pool = SQLiteConnectionPool("ec2.db")

    # Use mock_aws module to simulate AWS cli calls and provide mocked console logging
    # Note: mock_aws does not handle parameter validation real cli deployment would report*
    with mock_aws():
        ui = UserInterface()
        llm_interface = LLMInterface()
        ec2_cli = EC2CLI(logging_function=ui.log_to_user)
        agent = AWSAgent(ui, ec2_cli, llm_interface, run_reflection=True)

        agent.run()


if __name__ == "__main__":
    main()
