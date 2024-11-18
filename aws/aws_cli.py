import boto3
import time
from datetime import datetime
from dataclasses import dataclass, field
from typing import List, Optional, Dict
from botocore.exceptions import ClientError
import logging

logger = logging.getLogger("aws_agent_logger")


class AWSConfig:
    """
    A class that represents an AWS configuration object.
    Used as a base class for other AWS configuration dataclasses.
    """

    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)

    def to_dict(self) -> Dict:
        """
        A method that converts the object attributes to a dictionary excluding None values.

        Returns:
            Dict: A dictionary containing non-None attributes.
        """
        return {k: v for k, v in self.__dict__.items() if v is not None}

    def modify_config(self, logging_function=print, **kwargs):
        """
        Modify the configuration attributes of the object based on the provided keyword arguments.

        Args:
            **kwargs (dict): Keyword arguments to modify the configuration attributes.

        Returns:
            None
        """

        for key, value in kwargs.items():
            # We want LLM to only modify keys specified by user
            # By making defaults None in the function call, we can encourage LLM to not hallucinate values
            # Then values sent as None to this function will be ignored - i.e. don't want to change them
            if value is not None:
                if hasattr(self, key):
                    setattr(self, key, value)
                    logger.info(f"Modifying {key} to {value}")
                else:
                    """
                    raise AttributeError(
                        f"{self.__class__.__name__} has no attribute '{key}'"
                    )
                    """
                    logging_function(
                        f"\n{self.__class__.__name__} has no attribute '{key}'. Please select a valid parameter to modify."
                    )


@dataclass
class EC2InstanceConfig(AWSConfig):
    """
    Dataclass for EC2 config -
        a. With autoscaling --> create launch template from
        b. Without autoscaling --> create EC2 instances with run_instances

    Note: Alternatively can use Pydantic base model class for function calling argument validation
    """

    InstanceType: Optional[str] = None
    ImageId: str = "ami-0984f4b9e98be44bf"
    MinCount: int = 1
    MaxCount: int = 1

    # Parameter extension ex -
    # TagSpecifications: List[Dict] = field(default_factory=list)


@dataclass
class AutoScalingConfig(AWSConfig):
    """
    Dataclass for Autoscaling config - used for create_autoscaling_group
    """

    MinSize: int = 1
    MaxSize: int = 1
    DesiredCapacity: int = 1

    # default values
    LaunchTemplateName: str = "test"
    VPCZoneIdentifier: str = "subnet-test-1"
    AvailabilityZones: List[str] = field(default_factory=lambda: ["us-east-1a"])


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
