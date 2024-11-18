# aws_agent

## Description

Self-reflecting AI Agent architecture for allowing users to create, modify, and deploy AWS CLI commands with natural language.


## Setup and Run 

```
./setup_and_run.sh
```

## Data Initialization
A local csv file containing information on EC2 instances (cpu, ram, network performance, on demand cost, etc) is stored in /data.
Upon script start, a SQLite db is created locally with an 'ec2_rec' table.   


## User Flow
1. User is first prompted to enter EC2 requirements in terms of CPU and/or RAM

2. The agent is able to determine the user's intent and run SQL code to find the cheapest instance type per the given requirements (in terms of on demand cost).

3. Throughout the proceeding dialogue flow, the user is able to enable autoscaling, change the initial RAM/CPU requirements, modify the EC2 or autoscaling config, display the current configs, and confirm deployment.

4. After config is confirmed and the user indicates readiness to deploy, the system simulates the AWS calls to launch the requisite instances and streams console logs from one of the launched instances to the user by default (simulated calls done here with moto package).

*An out-of-scope intent is employed by the agent to handle queries by the user outside the covered fucntionality. 

## System Flow (after initial requirements gathering at start)
1. Get user query
2. Send query and conversation history to LLM to generate most appropriate function call with arguments at current dialogue step
3. Send query, conversation history, and first LLM generation to LLM endpoint again to reflect and modify call as needed
4. Final function call prediction parsed
5. Run action associated with parsed function call - generally involves modifying config state or deploying if not out-of-scope
6. Get user feedback (if didn't deploy in (5))

## Usage Examples

1. Find instance with minimum cost per requirements - '4 RAM', 'get cheapest instance with 3 RAM and 2 CPU'
2. Modify the EC2 config - 'change min count to 2 and max count to 4' 
3. Modify the autoscaling config - 'change desired capacity to 5 and launch template name to test'
4. Display current config - 'display config', 'show deployment settings', etc
5. Deploy - 'config looks good', 'deploy' 

## Concepts

#### Functionality

The system hits the endpoint of an open-source LLM (NexusRaven) that has achieved high performance on function-calling benchmarks.
In this code, we treat the LLM function-calling response as an intent router - routing to the appropriate application code with associated function arguments.
One example of an intent is to modify the EC2 config state - where the EC2 config is represented in the application as a dataclass. 
Queries such as 'change the minSize to 4', when incorporated in the function-calling prompt, would direct the LLM to predict 'modify_ec2_config(minSize=4)' as an example.   

The user interface is kept simple through a CLI. Logging and error handling very basic (not intended to be anything like production code**).  

#### Extensibility

We are able to scale the number of intents within the system simply by expanding the model's prompt template. 
Should the number of intents become large, it may become appropriate to implement a series of routers chained - ex first router routes to a cli decision engine --> engine routes to correct cli call. This would reduce the average # tokens per LLM call vs storing everything in one large prompt (saving on latency and cost). 

With a more thorough AWS data source, the system would be able to identify optimal infrastructure with more parameters (ex # GPUs) with minor modifications to the application. 

Can subsitute any LLM optimized for function-calling. Running an LLM locally to hit was also considered as an alternative, ex Llama 3.2 w/Chat Ollama.

The system was done outisde of a common LLM app framework (ex LangChain) to show effect of simpler helper tools to create a functioning agent. 
Extending this code's functionality (ex advanced memory, more complex routing, diversified output parsing), using the built-in tools from frameworks like this would likely prove useful.  

#### Preventing Hallucinations 

The primary focus of this design was to defer to application logic wherever possible to mitigate model hallucinations.
As an example, here we have the application code taking input CPU and RAM to format a SQL query string as opposed to generating the SQL code directly from the LLM.  
This was done to eliminate the risks of improperly generated SQL code in addition to unintended consequences such as data corruption. 
Text-2-SQL is an ongoing research area that has shown promise in recent developments - given the scope of SQL generation is incredibly small in this use-case as well as extended ones, the risks didn't justify the approach here, but it could be considered should the complexity requirements drastically increase.

The out-of-scope intent was also created to mitigate hallucinations and for error-handling in most cases - ie if model doesn't see a relevant intent or hypothetically generated an un-parseable function call (ex standard text). 

Prompting was also an area of focus - clean, direct function docstrings and function argument descriptions. 

