import boto3
import time
from datetime import datetime
from typing import List, Optional, Dict, Callable
from botocore.exceptions import ClientError
import logging
from pydantic import BaseModel, Field, model_validator, SkipValidation

logger = logging.getLogger("aws_agent_logger")

class AWSConfig(BaseModel):
    """
    Base Config class for AWS CLI deployment configurations

    Inherited by EC2 Config and AutoScaling Config
    """

    # adding hook for logging to user - option to rework scripts to not do within class itself
    logging_function: SkipValidation[Callable] = print
    class Config:
        arbitrary_types_allowed = True

    def to_dict(self, exclude_none: bool = True)->Dict:
        """
        Convert the model instance to a dictionary.

        Args:
            exclude_none (bool): If True, exclude fields with None values.

        Returns:
            Dict: A dictionary representation of the model's fields.
        """

        data = self.model_dump(exclude_none=exclude_none)
        # remove the logging_function from the output
        data.pop('logging_function', None)
        return data

    def modify_config(self, **kwargs):
        """
        Modify the config based on the provided keyword arguments.

        Args:
            **kwargs: argument names and values to modify the config; values of None are ignored
                      since predicted from function calling response
        """

        new_data = self.model_dump()

        for key, value in kwargs.items():
            if hasattr(self, key):
                if value is not None:
                    new_data[key] = value
            else:
                self.logging_function(
                    f"{self.__class__.__name__} has no attribute '{key}'. Please select a valid parameter to modify.")

        # try to create a new instance with the updated data
        try:
            new_instance = self.__class__.model_validate(new_data)

            # if validation passes, update self with new values
            for key, value in new_data.items():
                setattr(self, key, value)

            return self

        except ValueError as e:
            # if validation fails, log the error and return the original instance without changes
            error_message = e.errors()[0]['msg'].replace('Value error, ', '')
            self.logging_function(f"\nThe modifications you specified are invalid. {error_message}")
            return self


class EC2InstanceConfig(AWSConfig):
    """
    Pydantic class for EC2 config - used for deployment run_instances
    """

    InstanceType: str | None = None
    ImageId: str = 'ami-0984f4b9e98be44bf'
    MinCount: int = Field(default=1, ge=1)
    MaxCount: int = Field(default=1, ge=1)

    @model_validator(mode='after')
    def validate_counts(self):
        if self.MinCount > self.MaxCount:
            raise ValueError('MaxCount must be greater than MinCount. Try changing both values in the same query.')
        return self


class AutoScalingConfig(AWSConfig):
    """
    Pydantic class for Autoscaling config - used for create_autoscaling_group
    """

    MinSize: int = Field(default=1, ge=1)
    MaxSize: int = Field(default=1, ge=1)
    DesiredCapacity: int = Field(default=1, ge=1)

    # default values
    LaunchTemplateName: str = "test"
    VPCZoneIdentifier: str = "subnet-test-1"
    AvailabilityZones: List[str] = Field(default_factory=lambda: ["us-east-1a"])

    @model_validator(mode='after')
    def validate_counts(self):
        if self.MinSize > self.MaxSize:
            raise ValueError('MaxSize must be greater than MinSize. Try changing both in the same query.')
        if self.DesiredCapacity < self.MinSize or self.DesiredCapacity > self.MaxSize:
            raise ValueError('DesiredCapacity must be between MinSize and MaxSize')

        return self

class AWSCLIBase:
    """
    Base Class for AWS cli operations

    Args:
        region_name (str): The AWS region name to use to initialize boto3 session. Defaults to "us-east-1".
    """

    def __init__(self, region_name="us-east-1"):
        self.session = boto3.Session(
            aws_access_key_id="test",
            aws_secret_access_key="test",
            region_name=region_name,
        )

    def deploy(self, **kwargs):
        raise NotImplementedError("Subclass must implement abstract method")

    def verify_creation(self, **kwargs):
        raise NotImplementedError("Subclass must implement abstract method")

    def stream_logs(self, **kwargs):
        raise NotImplementedError("Subclass must implement abstract method")


class EC2CLI(AWSCLIBase):
    """
    Base Class for AWS cli operations

    Args:
        region_name (str): The AWS region name to use to initialize boto3 session. Defaults to "us-east-1".
    """

    def __init__(self, region_name="us-east-1", logging_function=print):
        super().__init__(region_name)
        self.vpc_id = None
        self.subnet_id = None
        self.ec2_client = self.session.client("ec2", region_name=region_name)
        self.as_client = self.session.client("autoscaling", region_name=region_name)

        # create mock vpc / subnet
        self.initiate_vpc_subnet()

        # generic logging function - in this case, just printing to console
        self.logging_function = logging_function
        self.deployed_instance_ids = []

    def initiate_vpc_subnet(
            self,
            vpc_cidr_block="10.0.0.0/16",
            subnet_cidr_block="10.0.0.0/24",
            subnet_availability_zone="us-east-1a",
    ):
        """
        Generate a VPC and subnet in AWS using the specified CIDR blocks and availability zone.

        Args:
            vpc_cidr_block (str): The CIDR block for the VPC. Defaults to "10.0.0.0/16".
            subnet_cidr_block (str): The CIDR block for the subnet. Defaults to "10.0.0.0/24".
            subnet_availability_zone (str): The availability zone for the subnet. Defaults to "us-east-1a".

        Returns:
            None
        """

        vpc_response = self.ec2_client.create_vpc(CidrBlock=vpc_cidr_block)
        self.vpc_id = vpc_response["Vpc"]["VpcId"]

        subnet_response = self.ec2_client.create_subnet(
            VpcId=self.vpc_id,
            CidrBlock=subnet_cidr_block,
            AvailabilityZone=subnet_availability_zone,
        )
        self.subnet_id = subnet_response["Subnet"]["SubnetId"]

    def create_launch_template(
            self, ec2_config: EC2InstanceConfig, template_name: str = "test"
    ) -> Optional[str]:
        """
        Creates a launch template based on the provided configuration.

        Args:
            ec2_config (EC2InstanceConfig): The configuration settings for the launch template.
            template_name (str): The name of the launch template. Defaults to "test".

        Returns:
            Optional[str]: The ID of the created launch template, or None if an error occurred.
        """

        try:
            response = self.ec2_client.create_launch_template(
                LaunchTemplateName=template_name,
                LaunchTemplateData={
                    "ImageId": ec2_config.ImageId,
                    "InstanceType": ec2_config.InstanceType,
                },
            )
            return response["LaunchTemplate"]["LaunchTemplateId"]
        except ClientError as e:
            self.logging_function(f"Error creating launch template: {e}")
            return None

    def create_auto_scaling_group(
            self, as_config: AutoScalingConfig, launch_template_id: str
    ):
        """
        Creates an auto-scaling group based on the provided configuration and launch template.

        Args:
            as_config (AutoScalingConfig): The configuration settings for the auto-scaling group.
            launch_template_id (str): The ID of the launch template to use.

        Returns:
            None
        """

        try:
            self.as_client.create_auto_scaling_group(
                AutoScalingGroupName=f"ASG-{as_config.LaunchTemplateName}",
                MinSize=as_config.MinSize,
                MaxSize=as_config.MaxSize,
                DesiredCapacity=as_config.DesiredCapacity,
                AvailabilityZones=as_config.AvailabilityZones,
                VPCZoneIdentifier=as_config.VPCZoneIdentifier,
                LaunchTemplate={
                    "LaunchTemplateId": launch_template_id,
                    "Version": "$Latest",
                },
            )
            self.logging_function(
                f"Auto Scaling Group 'ASG-{as_config.LaunchTemplateName}' created successfully."
            )
        except ClientError as e:
            self.logging_function(f"Error creating Auto Scaling group: {e}")

    def deploy(
            self,
            ec2_config: EC2InstanceConfig,
            as_config: AutoScalingConfig,
            autoscaling_enabled: bool = False,
    ):
        """
        Deploy EC2 instances and optionally create an Auto Scaling Group.

        Args:
            ec2_config (EC2InstanceConfig): Configuration for the EC2 instances.
            as_config (AutoScalingConfig): Configuration for the Auto Scaling Group.
            autoscaling_enabled (bool, optional): Flag to enable Auto Scaling. Defaults to False.

        Returns:
            None
        """

        self.logging_function("\n")

        try:
            if autoscaling_enabled:
                launch_template_id = self.create_launch_template(
                    ec2_config, as_config.LaunchTemplateName
                )

                if not launch_template_id:
                    self.logging_function(
                        "Failed to create Launch Template. Aborting deployment."
                    )
                    return

                self.logging_function(
                    f"Launch Template created with ID: {launch_template_id}"
                )

                self.logging_function("Creating Auto Scaling Group...")
                self.create_auto_scaling_group(as_config, launch_template_id)

                self.logging_function(
                    "Waiting for instances to be launched by Auto Scaling Group..."
                )
                time.sleep(10)  # time to allow instances to launch

                response = self.as_client.describe_auto_scaling_groups(
                    AutoScalingGroupNames=[f"ASG-{as_config.LaunchTemplateName}"]
                )
                if response["AutoScalingGroups"]:
                    instance_ids = [
                        instance["InstanceId"]
                        for instance in response["AutoScalingGroups"][0]["Instances"]
                    ]

                    self.logging_function(
                        f"Auto Scaling Group has launched {len(instance_ids)} instances. Instance IDs: {', '.join(instance_ids)}"
                    )

                else:
                    self.logging_function(
                        "No instances have been launched yet by the Auto Scaling Group."
                    )
                    return
            else:
                self.logging_function("Deploying EC2 instances directly...")
                response = self.ec2_client.run_instances(**ec2_config.to_dict())
                instance_ids = [
                    instance["InstanceId"] for instance in response["Instances"]
                ]
                self.logging_function(
                    f"Deployed {len(instance_ids)} instances. Instance IDs: {', '.join(instance_ids)}"
                )

            self.deployed_instance_ids += instance_ids
            self.logging_function("Deployment completed successfully")

            # per requirements - stream logs to user - could send all instances created
            # to make it more user-friendly here, will just stream one instance logs
            self.stream_logs_from_ec2_instance(instance_ids[0])

        except Exception as e:
            self.logging_function(f"An error occurred during deployment: {str(e)}")

    def verify_ec2_instance_creation(self, instance_id) -> str:
        """
        Verify the creation of an EC2 instance.

        Args:
            instance_id (str): The ID of the EC2 instance.

        Returns:
            str: The state of the EC2 instance.
        """
        try:
            response = self.ec2_client.describe_instances(InstanceIds=[instance_id])
            state = response["Reservations"][0]["Instances"][0]["State"]["Name"]
            return state
        except Exception as e:
            return str(e)

    def get_ec2_instance_console_output(self, instance_id) -> str:
        """
        Get the console output of a specific EC2 instance.

        Args:
            instance_id (str): The ID of the EC2 instance.

        Returns:
            str: The console output of the EC2 instance.
        """

        response = self.ec2_client.get_console_output(InstanceId=instance_id)
        output = response["Output"]
        return output

    def stream_logs_from_ec2_instance(self, instance_id, interval=5, duration=30):
        """
        Function to stream logs from a specific EC2 instance for a specified duration.

        Args:
            instance_id (str): The ID of the EC2 instance to stream logs from.
            interval (int): The interval in seconds between each log stream (default is 5 seconds).
            duration (int): The total duration in seconds to stream logs for (default is 30 seconds).

        Returns:
            None
        """

        end_time = time.time() + duration

        while time.time() < end_time:
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            console_output = self.get_ec2_instance_console_output(instance_id)

            self.logging_function(
                f"{current_time} - {instance_id} Console Output: {console_output}"
            )

            time.sleep(interval)
