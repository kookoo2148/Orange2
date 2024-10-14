# https://github.com/aws-samples/aws-cdk-examples/tree/main/python/codepipeline-build-deploy-github-manual
import os
from aws_cdk import (
    aws_codecommit as codecommit,
    aws_ecr as ecr,
    aws_ecs as ecs,
    aws_codebuild as codebuild,
    aws_lambda as lambda_,
    aws_iam as iam,
    aws_ec2 as ec2,
    aws_elasticloadbalancingv2 as elb,
    aws_autoscaling as autoscaling,
    aws_codepipeline as pipeline,
    aws_codepipeline_actions as pipelineactions,
    aws_codedeploy as codedeploy,
    custom_resources as custom,
    Stack,
    CfnOutput,
    SecretValue
)
from datetime import datetime
from aws_cdk.custom_resources import Provider
from constructs import Construct
from aws_cdk.aws_ecr_assets import DockerImageAsset

prefix = "Orange-ECR-Stack"

class orangeecrstack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        
        # # Creates an AWS CodeCommit repository
        # code_repo = codecommit.Repository(
        #     self, "CodeRepo",
        #     repository_name="koo-repo1",
        #     # Copies files from app directory to the repo as the initial commit
        #     code=codecommit.Code.from_directory("app", "main")
        # )
        
        # Creates an Elastic Container Registry (ECR) image repository
        image_repo = ecr.Repository(self, "OrangeImageRepo")

        # Creates a Task Definition for the ECS EC2 instances
        ec2_task_def = ecs.Ec2TaskDefinition(self, "OrangetaskDefinition",
            network_mode=ecs.NetworkMode.AWS_VPC)
        
        # Adding container
        ec2_task_def.add_container(
            "Container",
            container_name="orange-nvidia-sample-container",
            image=ecs.ContainerImage.from_ecr_repository(image_repo),
            memory_reservation_mib=1024,
            port_mappings=[{"containerPort": 80}]
        )
        
        # CodeBuild project USING Github that builds the Docker image ##########WITH GITHUB
        build_image = codebuild.Project(
            self, "BuildImage",
            build_spec=codebuild.BuildSpec.from_source_filename(
                "buildspec.yaml"),
            source=codebuild.Source.git_hub(
                owner="kookoo2148",    # TODO: Replace with your GitHub username
                repo="Orange1",   # TODO: Replace with your GitHub repository name
                branch_or_ref="main",
            ),
            environment=codebuild.BuildEnvironment(
                privileged=True
            ),
            environment_variables={
                "AWS_ACCOUNT_ID": codebuild.BuildEnvironmentVariable(value=os.getenv('CDK_DEFAULT_ACCOUNT') or ""),
                "REGION": codebuild.BuildEnvironmentVariable(value=os.getenv('CDK_DEFAULT_REGION') or ""),
                "IMAGE_TAG": codebuild.BuildEnvironmentVariable(value="latest"),
                "IMAGE_REPO_NAME": codebuild.BuildEnvironmentVariable(value=image_repo.repository_name),
                "REPOSITORY_URI": codebuild.BuildEnvironmentVariable(value=image_repo.repository_uri),
                "TASK_DEFINITION_ARN": codebuild.BuildEnvironmentVariable(value=ec2_task_def.task_definition_arn),
                "TASK_ROLE_ARN": codebuild.BuildEnvironmentVariable(value=ec2_task_def.task_role.role_arn),
                "EXECUTION_ROLE_ARN": codebuild.BuildEnvironmentVariable(value=ec2_task_def.execution_role.role_arn)
            }
        )
        
        # # CodeBuild project that builds the Docker image ########################## WITH REPO
        # build_image = codebuild.Project(
        #     self, "BuildImage",
        #     build_spec=codebuild.BuildSpec.from_source_filename(
        #         "buildspec.yaml"),
        #     source=codebuild.Source.code_commit(
        #         repository=code_repo,
        #         branch_or_ref="main"
        #     ),
        #     environment=codebuild.BuildEnvironment(
        #         privileged=True
        #     ),
        #     environment_variables={
        #         "AWS_ACCOUNT_ID": codebuild.BuildEnvironmentVariable(value=os.getenv('CDK_DEFAULT_ACCOUNT') or ""),
        #         "REGION": codebuild.BuildEnvironmentVariable(value=os.getenv('CDK_DEFAULT_REGION') or ""),
        #         "IMAGE_TAG": codebuild.BuildEnvironmentVariable(value="latest"),
        #         "IMAGE_REPO_NAME": codebuild.BuildEnvironmentVariable(value=image_repo.repository_name),
        #         "REPOSITORY_URI": codebuild.BuildEnvironmentVariable(value=image_repo.repository_uri),
        #         "TASK_DEFINITION_ARN": codebuild.BuildEnvironmentVariable(value=ec2_task_def.task_definition_arn),
        #         "TASK_ROLE_ARN": codebuild.BuildEnvironmentVariable(value=ec2_task_def.task_role.role_arn),
        #         "EXECUTION_ROLE_ARN": codebuild.BuildEnvironmentVariable(value=ec2_task_def.execution_role.role_arn)
        #     }
        # )
        # Grants CodeBuild project access to pull/push images from/to ECR repo
        image_repo.grant_pull_push(build_image)
        
        # Creates VPC for the ECS Cluster
        cluster_vpc = ec2.Vpc(
            self, "OrangeClusterVpc",
            ip_addresses=ec2.IpAddresses.cidr(cidr_block="10.75.0.0/16")
        )
        
        # Create cluster
        cluster = ecs.Cluster(self, "Cluster",
            vpc=cluster_vpc
        )
        
        auto_scaling_group = autoscaling.AutoScalingGroup(self, "ASG",
            instance_type=ec2.InstanceType("g5.4xlarge"),
            machine_image=ecs.EcsOptimizedImage.amazon_linux2(),
            vpc=cluster_vpc,
            desired_capacity=2,
        )
        
        capacity_provider = ecs.AsgCapacityProvider(self, "testingCapacityProvider",
            auto_scaling_group=auto_scaling_group
        )
        
        cluster.add_asg_capacity_provider(capacity_provider)
        
        
        # Creates an ECS EC2 Instance
        ec2_service = ecs.Ec2Service(
            self, "Ec2Service",
            task_definition=ec2_task_def,
            cluster=cluster,
            # capacity_provider_strategies=[ecs.CapacityProviderStrategy(
            #     capacity_provider=capacity_provider.capacity_provider_name,
            #     weight=1)],
            # Sets CodeDeploy as the deployment controller
            deployment_controller=ecs.DeploymentController(
                type=ecs.DeploymentControllerType.CODE_DEPLOY
            ),
        )
        
         # Lambda function that triggers CodeBuild image build project
        trigger_code_build = lambda_.Function(
            self, "BuildLambda",
            architecture=lambda_.Architecture.ARM_64,
            code=lambda_.Code.from_asset("./lambda/trigger"),
            handler="trigger-build.handler",
            runtime=lambda_.Runtime.NODEJS_18_X,
            environment={
                "CODEBUILD_PROJECT_NAME": build_image.project_name,
                "REGION": os.getenv('CDK_DEFAULT_REGION') or ""
            },
            # Allows this Lambda function to trigger the buildImage CodeBuild project
            initial_policy=[
                iam.PolicyStatement(
                    effect=iam.Effect.ALLOW,
                    actions=["codebuild:StartBuild"],
                    resources=[build_image.project_arn]
                )
            ]
        )
        
        # Triggers a Lambda function using AWS SDK  <<<<<<<<<--------------ASK IF I CAN USE CUSTOM RESOURCE
        trigger_lambda = custom.AwsCustomResource(
            self, "BuildLambdaTrigger",
            install_latest_aws_sdk=True,
            policy=custom.AwsCustomResourcePolicy.from_statements([
                iam.PolicyStatement(
                    effect=iam.Effect.ALLOW,
                    actions=["lambda:InvokeFunction"],
                    resources=[trigger_code_build.function_arn],
                )
            ]),
            on_create={
                "service": "Lambda",
                "action": "invoke",
                "physical_resource_id": custom.PhysicalResourceId.of("id"),
                "parameters": {
                    "FunctionName": trigger_code_build.function_name,
                    "InvocationType": "Event",
                },
            },
            on_update={
                "service": "Lambda",
                "action": "invoke",
                "parameters": {
                    "FunctionName": trigger_code_build.function_name,
                    "InvocationType": "Event",
                },
            }
        )

        # Deploys the cluster VPC after the initial image build triggers
        cluster_vpc.node.add_dependency(trigger_lambda)
        
        # Creates a new blue Target Group that routes traffic from the public Application Load Balancer (ALB) to the
        # registered targets within the Target Group e.g. (EC2 instances, IP addresses, Lambda functions)
        # https://docs.aws.amazon.com/elasticloadbalancing/latest/application/load-balancer-target-groups.html
        target_group_blue = elb.ApplicationTargetGroup(
            self, "BlueTargetGroup",
            target_group_name="alb-blue-tg",
            target_type=elb.TargetType.IP,
            port=80,
            vpc=cluster_vpc
        )

        # Creates a new green Target Group
        target_group_green = elb.ApplicationTargetGroup(
            self, "GreenTargetGroup",
            target_group_name="alb-green-tg",
            target_type=elb.TargetType.IP,
            port=80,
            vpc=cluster_vpc
        )

        # Creates a Security Group for the Application Load Balancer (ALB)
        alb_sg = ec2.SecurityGroup(
            self, "ALBSecurityGroup",
            vpc=cluster_vpc,
            allow_all_outbound=True
        )
        alb_sg.add_ingress_rule(
            peer=ec2.Peer.any_ipv4(),
            connection=ec2.Port.tcp(80),
            description="Allows access on port 80/http",
            remote_rule=False
        )

        # Creates the ALB
        application_load_balancer = elb.ApplicationLoadBalancer(
            self, "OrangeALB",
            vpc=cluster_vpc,
            internet_facing=True,
            security_group=alb_sg
        )
        
        # Adds a listener on port 80 to the ALB
        alb_listener = application_load_balancer.add_listener(
            "AlbListener80",
            # open=True,
            open=False,
            port=80,
            default_target_groups=[target_group_blue]
        )
        
        # Adds the ECS ec2 service to the ALB target group
        ec2_service.attach_to_application_target_group(target_group_blue)
        
        # Creates new pipeline artifacts
        source_artifact = pipeline.Artifact("SourceArtifact")
        build_artifact = pipeline.Artifact("BuildArtifact")

        # Creates the source stage for CodePipeline <<<<<<<<<- for github
        source_stage = pipeline.StageProps(
            stage_name="Source",
            actions=[
                pipelineactions.GitHubSourceAction(
                    action_name="GitHub",
                    owner='kookoo2148',    # TODO: Replace with your GitHub username
                    repo='Orange1',   # TODO: Replace with your GitHub repository name
                    branch="main",
                    oauth_token=SecretValue.secrets_manager("github-access-token-secret"),
                    output=source_artifact,
                )
            ]
        )
        
        # # Creates the source stage for ######CodePipeline
        # source_stage = pipeline.StageProps(
        #     stage_name="Source",
        #     actions=[
        #         pipelineactions.CodeCommitSourceAction(
        #             action_name="CodeCommit",
        #             branch="main",
        #             output=source_artifact,
        #             repository=code_repo
        #         )
        #     ]
        # )
        
        # Creates the build stage for CodePipeline
        build_stage = pipeline.StageProps(
            stage_name="Build",
            actions=[
                pipelineactions.CodeBuildAction(
                    action_name="DockerBuildPush",
                    input=pipeline.Artifact("SourceArtifact"),
                    project=build_image,
                    outputs=[build_artifact]
                )
            ]
        )

        # Creates a new CodeDeploy Deployment Group
        deployment_group = codedeploy.EcsDeploymentGroup(
            self, "CodeDeployGroup",
            service=ec2_service,
            # Configurations for CodeDeploy Blue/Green deployments
            blue_green_deployment_config=codedeploy.EcsBlueGreenDeploymentConfig(
                listener=alb_listener,
                blue_target_group=target_group_blue,
                green_target_group=target_group_green
            )
        )

        # Creates the deploy stage for CodePipeline
        deploy_stage = pipeline.StageProps(
            stage_name="Deploy",
            actions=[
                pipelineactions.CodeDeployEcsDeployAction(
                    action_name="EcsEC2Deploy",
                    app_spec_template_input=build_artifact,
                    task_definition_template_input=build_artifact,
                    deployment_group=deployment_group
                )
            ]
        )
        
        # Store Github credentials to CodeBuild <<<<<<<<<<<<<<<-------- for github
        codebuild.GitHubSourceCredentials(self, "CodeBuildGitHubCreds",
            access_token=SecretValue.secrets_manager("github-access-token-secret")
        )


        # Creates an AWS CodePipeline with source, build, and deploy stages
        pipeline.Pipeline(
            self, "BuildDeployPipeline",
            pipeline_name="ImageBuildDeployPipeline",
            stages=[source_stage, build_stage, deploy_stage]
        )

        # Outputs the ALB public endpoint
        CfnOutput(
            self, "PublicAlbEndpoint",
            value=f"http://{application_load_balancer.load_balancer_dns_name}"
        )
        
        
