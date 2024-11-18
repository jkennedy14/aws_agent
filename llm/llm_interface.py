import requests
import ast
from typing import Dict, List, Union, Optional
import config
import logging

logger = logging.getLogger("aws_agent_logger")


class LLMInterface:
    """
    Interface for all LLM calls and output parsing
    """

    def __init__(self):
        # We're essentially using this prompt below as a router / intent classifier
        # Scaling function calls from here --> Can add multiple routers chained
        # ex first router routes to for ex cli decision engine --> engine routes to correct cli call

        self.function_list = '''
            Function:
            def user_intent_ec2_type_selection(cpu: Optional[int] = None, ram: Optional[float] = None):
                """
                Finds the most suitable AWS EC2 instance type given user specified cpu and ram requirements. 
                
                Args:
                - cpu (Optional[int]): The desired number of CPU cores.
                - ram (Optional[float]): The desired amount of RAM in gigabytes. 
                
                Examples: '2 ram and 1 cpu', '3 cpu', '4 ram'
                """
            
            Function:
            def user_intent_confirm():
                """
                Checks if user wants to proceed with deployment. 
                Suitable if User answers in the affirmative that the deployment looks good.
                The function takes no arguments.
                Examples: 'yes' or 'looks good'
                """
                
            Function:
            def user_intent_enable_autoscaling():
                """
                Function called when user wants to enable autoscaling for the deployment.
                The function takes no arguments. 
                Examples: 'enable autoscaling' or 'autoscaling'
                """
                
            Function:
            def user_intent_display_current_deployment_config():
                """
                Displays current deployment settings. Ran if user asks to see current config.
                The function takes no arguments.
                Examples: 'show config' or 'display deployment settings' or 'display current config'
                """
                
            Function:
            def user_intent_modify_ec2_config(
                InstanceType: Optional[str] = None,
                ImageId: Optional[str] = None,
                MinCount: Optional[int] = None,
                MaxCount: Optional[int] = None,
            ):
                """
                Function called when user wants to modify the current ec2 config. 
                In many instances, only one parameter will be modified and the rest will be None.
                In others, the user may specify more than one parameter. The ones not specified will be None.
                In some instances, all parameters may be None if user specifies a parameter that doesn't exist. 
                
                Args:
                - InstanceType (Optional[str]): The desired instance type.
                - ImageId (Optional[str]): The desired image ID.
                - MinCount (Optional[int]): The desired minimum number of instances.
                - MaxCount (Optional[int]): The desired maximum number of instances.
                
                Examples: 'change ec2 min count to 3', 'modify max count to 5', 'change instance type to t3.large'
                """
                
            Function:
            def user_intent_modify_as_config(
                LaunchTemplateName: Optional[str] = None,
                VPCZoneIdentifier: Optional[str] = None,
                AvailabilityZones: Optional[List[str]] = None,
                MinSize: Optional[int] = None,
                MaxSize: Optional[int] = None,
                DesiredCapacity: Optional[int] = None
            ):
                """
                Function called when user wants to modify the current autoscaling config. 
                In many instances, only one parameter will be modified and the rest will be None.
                In others, the user may specify more than one parameter. The ones not specified will be None.
                In some instances, all parameters may be None if user specifies a parameter that doesn't exist. 
                
                Args:
                - LaunchTemplateName (Optional[str]): The desired launch template name.
                - VPCZoneIdentifier (Optional[str]): The desired VPC zone identifier.
                - AvailabilityZones (Optional[List[str]]): The desired availability zones.
                - MinSize (Optional[int]): The desired minimum number of instances.
                - MaxSize (Optional[int]): The desired maximum number of instances.
                - DesiredCapacity (Optional[int]): The desired number of instances.
                
                Examples: 'change autoscaling min size to 3', 'modify max size to 6', 'change desired capacity to 5', 
                'change availability zones to us-east-1a and us-easy-1b', 'set launch template name to test'
                """
                
            Function:
            def user_intent_out_of_scope():
                """
                Call this function if user query doesn't relate to any other function call defined above.
                Do not use to fill in for other function parameters.
                The function takes no arguments.
                Example: 'Hello' or 'what's the capital of France'
                """
        '''

        self.function_calling_prompt = """
            <human>
            
            {function_list}
            
            Conversation History:
            {history}
            
            Current User Query: {query}
            <human_end>
            """

        self.reflective_prompt = """
            <human>
            
            {function_list}
            
            Conversation History:
            {history}
            
            Current User Query: {query}
            
            <human_end>
            """

    @staticmethod
    def convert_raven_function_calling_response_to_function_name_and_args(
            llm_response: str,
    ) -> Dict:
        """
        Converts a Raven function calling response into a function name and arguments dictionary.
        Function also used to change string to ints and floats where needed.
        This is important for argument type validation from LLM --> calling functions

        Note: This function structure is to handle 1 function call at a time.
        Howvever, easily extensible to multiple function calls (a(); b();) and nested function calls (a(arg = b()))

        Args:
            llm_response (str): The Raven function calling response string ex 'find_best_instance(cpu=4, ram=8.0)'

        Returns:
            Dict: A dictionary containing the function name and its keyword arguments.
        """

        # out of scope response standardized - if not valid function called by router
        # Note: this reduces the diversity of LLM responses
        # If wanted agent to respond creatively in situations - would remove the out of scope intent here
        out_of_scope_response = {
            "function_name": "user_intent_out_of_scope",
            "kwargs": {},
        }

        try:
            # parse the string into an AST
            parsed = ast.parse(llm_response)

            if len(parsed.body) != 1 or not isinstance(parsed.body[0], ast.Expr):
                logger.info("LLM function call prediction not a single function call")
                return out_of_scope_response

            call = parsed.body[0].value
            if not isinstance(call, ast.Call):
                logger.info("LLM function call prediction not a function call")
                return out_of_scope_response

            # extract function name
            if isinstance(call.func, ast.Name):
                function_name = call.func.id
            elif isinstance(call.func, ast.Attribute):
                function_name = call.func.attr
            else:
                logger.info("LLM function call prediction unsupported function call")
                return out_of_scope_response

            # extract keyword arguments - can be empty
            # can be ints, floats, strings
            kwargs = {}
            for keyword in call.keywords:
                if isinstance(keyword.value, (ast.Str, ast.Num, ast.NameConstant)):
                    kwargs[keyword.arg] = ast.literal_eval(keyword.value)
                else:
                    kwargs[keyword.arg] = str(ast.dump(keyword.value))

            function_call_dict = {"function_name": function_name, "kwargs": kwargs}

            return function_call_dict

        except Exception as e:
            logger.error(
                "Error came up in parsing function calling response: " + str(e)
            )
            return out_of_scope_response

    @staticmethod
    def request_to_raven_endpoint(
            payload: Dict[str, Union[str, List, bool, float, int]]
    ) -> Dict:
        """
        Makes a request to the Raven LLM endpoint.

        Args:
            payload (Dict[str, Union[str, List, bool, float, int]]): The payload to send to the endpoint containing LLM parameters

        Returns:
            Dict: response from the endpoint containing LLM response
        """

        headers = {"Content-Type": "application/json"}

        response = requests.post(config.RAVEN_API_URL, headers=headers, json=payload)
        return response.json()

    def raven_llm_query(self, prompt: str) -> str:
        """
        A function that sends a request to the Raven endpoint with a prompt, retrieves the generated text, and returns it.

        Args:
            prompt (str): The prompt to be sent to the Raven endpoint.

        Returns:
            str: The generated output text after processing the response.
        """

        resp = self.request_to_raven_endpoint(
            {"inputs": prompt, "parameters": config.RAVEN_LLM_PARAMETERS}
        )

        output = resp[0]["generated_text"].replace("Call:", "").strip()

        return output

    def get_llm_function_calling_response(
            self, query: str, conversation_history: Optional[List[str]] = None
    ) -> Dict:
        """
        Gets the response of an LLM function call based on a query.
        Note: Inputting conversation history as input has very limited impact on performance in this use-case
            as all our current intents are naturally single-turn

        Args:
            query (str): The query used to make the function call.
            conversation_history (List[str], optional): The history of conversation strings. Defaults to an empty list.

        Returns:
            Dict: The response of the function call.
        """

        # Take up to -1 to remove last query and put at end as 'Current User Query'
        formatted_conversation_history = "\n".join(conversation_history[:-1])

        logger.info(f"Query sent for function call generation: {query}")
        logger.info(
            f"Conversation History sent for function call generation: {formatted_conversation_history}"
        )

        function_call_response_str = self.raven_llm_query(
            self.function_calling_prompt.format(
                function_list=self.function_list,
                history=formatted_conversation_history,
                query=query,
            )
        )

        logger.info(f"Function call response string: {function_call_response_str}")

        function_call_response_dict = (
            self.convert_raven_function_calling_response_to_function_name_and_args(
                function_call_response_str
            )
        )

        logger.info(
            f"Parsed function call and arguments: {function_call_response_dict}"
        )

        return function_call_response_dict

    def reflect(self, query, conversation_history: Optional[List[str]] = None) -> str:
        """
        Function reflectively analyzes previous user responses and the agent's current response
        to judge whether right function was called.

        Note: Generation logic exactly the same as reflection logic outside of what's included in conversation history as well
        as the prompt used. Could theoretically combine functions into one, but separated here for clarity

        Args:
            query (str): The query to be reflected.
            conversation_history (List[str], optional): The history of conversation strings. Defaults to an empty list.

        Returns:
            Dict: The response of the agent after reflection
        """

        # for reflection example here - consider whole conversation history including first agent generation
        formatted_conversation_history = "\n".join(conversation_history)

        logger.info(f"Query sent for function call generation: {query}")
        logger.info(
            f"Conversation History sent for function call generation: {formatted_conversation_history}"
        )

        reflection_function_call_response_str = self.raven_llm_query(
            self.reflective_prompt.format(
                function_list=self.function_list,
                history=formatted_conversation_history,
                query=query,
            )
        )

        logger.info(
            f"Reflection call response string: {reflection_function_call_response_str}"
        )

        reflection_function_call_response_dict = (
            self.convert_raven_function_calling_response_to_function_name_and_args(
                reflection_function_call_response_str
            )
        )

        logger.info(
            f"Parsed reflection function call and arguments: {reflection_function_call_response_dict}"
        )

        return reflection_function_call_response_dict
