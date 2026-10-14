# flyquery_sdk.AgentConversationsApi

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**create**](AgentConversationsApi.md#create) | **POST** /api/v1/agent/conversations | Create a conversation owned by the calling agent.
[**list_conversations**](AgentConversationsApi.md#list_conversations) | **GET** /api/v1/agent/conversations | List conversations for the agent&#39;s workspace (newest first).
[**post_turn**](AgentConversationsApi.md#post_turn) | **POST** /api/v1/agent/conversations/{conversation_id}/turn | Run a drill-down turn through the full query pipeline.
[**read**](AgentConversationsApi.md#read) | **GET** /api/v1/agent/conversations/{conversation_id} | Fetch a conversation with its turns.


# **create**
> ConversationRead create(x_agent_token, conversation_create, x_correlation_id=x_correlation_id, idempotency_key=idempotency_key)

Create a conversation owned by the calling agent.

Replay-dedup'd via ``Idempotency-Key`` (required). A retried
create otherwise allocates duplicate empty conversations the
agent has no way to clean up.

### Example

* Api Key Authentication (AgentToken):

```python
import flyquery_sdk
from flyquery_sdk.models.conversation_create import ConversationCreate
from flyquery_sdk.models.conversation_read import ConversationRead
from flyquery_sdk.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = flyquery_sdk.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure API key authorization: AgentToken
configuration.api_key['AgentToken'] = os.environ["API_KEY"]

# Uncomment below to setup prefix (e.g. Bearer) for API key, if needed
# configuration.api_key_prefix['AgentToken'] = 'Bearer'

# Enter a context with an instance of the API client
async with flyquery_sdk.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = flyquery_sdk.AgentConversationsApi(api_client)
    x_agent_token = 'fqt_live_aBcDeF1234567890aBcDeF1234567890' # str | Machine-to-machine bearer token. Replaces X-Tenant-Id and X-Workspace-Id on agent-tier endpoints -- the token's claims encode the tenant + workspace + scopes. Issue via ``POST /api/v1/agent-tokens``.
    conversation_create = flyquery_sdk.ConversationCreate() # ConversationCreate | 
    x_correlation_id = UUID('550e8400-e29b-41d4-a716-446655440000') # UUID | Optional client-supplied correlation id. The service uses this in every log line and downstream call. If absent the service mints a new UUID and echoes it in the response header. (optional)
    idempotency_key = 'ingest-2026-05-23-abc123' # str | Optional client-supplied idempotency key for mutating operations. The first request with a key persists its result; subsequent requests with the same key + same tenant return the cached response. Keys expire after 24h. (optional)

    try:
        # Create a conversation owned by the calling agent.
        api_response = await api_instance.create(x_agent_token, conversation_create, x_correlation_id=x_correlation_id, idempotency_key=idempotency_key)
        print("The response of AgentConversationsApi->create:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling AgentConversationsApi->create: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **x_agent_token** | **str**| Machine-to-machine bearer token. Replaces X-Tenant-Id and X-Workspace-Id on agent-tier endpoints -- the token&#39;s claims encode the tenant + workspace + scopes. Issue via &#x60;&#x60;POST /api/v1/agent-tokens&#x60;&#x60;. | 
 **conversation_create** | [**ConversationCreate**](ConversationCreate.md)|  | 
 **x_correlation_id** | **UUID**| Optional client-supplied correlation id. The service uses this in every log line and downstream call. If absent the service mints a new UUID and echoes it in the response header. | [optional] 
 **idempotency_key** | **str**| Optional client-supplied idempotency key for mutating operations. The first request with a key persists its result; subsequent requests with the same key + same tenant return the cached response. Keys expire after 24h. | [optional] 

### Return type

[**ConversationRead**](ConversationRead.md)

### Authorization

[AgentToken](../README.md#AgentToken)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**201** | Successful response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **list_conversations**
> PaginatedConversationRead list_conversations(x_agent_token, x_correlation_id=x_correlation_id)

List conversations for the agent's workspace (newest first).

### Example

* Api Key Authentication (AgentToken):

```python
import asyncio
import os

from flyquery_sdk import ApiClient, Configuration
from flyquery_sdk.api import AgentConversationsApi
from flyquery_sdk.exceptions import ApiException
from flyquery_sdk.models import PaginatedConversationRead


async def main():
    async with ApiClient(Configuration(host=os.environ["FLYQUERY_URL"])) as client:
        client.default_headers.update({
            "X-Tenant-Id": os.environ["FLYQUERY_TENANT_ID"],
            "X-Workspace-Id": os.environ["FLYQUERY_WORKSPACE_ID"],
        })
        api = AgentConversationsApi(client)
        try:
            page: PaginatedConversationRead = await api.list_conversations(
                x_agent_token=os.environ["FLYQUERY_AGENT_TOKEN"],
                _request_timeout=15.0,
            )
            print(page.total)
        except ApiException as exc:
            print(f"HTTP {exc.status}")
            raise


asyncio.run(main())
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **x_agent_token** | **str**| Machine-to-machine bearer token. Replaces X-Tenant-Id and X-Workspace-Id on agent-tier endpoints -- the token&#39;s claims encode the tenant + workspace + scopes. Issue via &#x60;&#x60;POST /api/v1/agent-tokens&#x60;&#x60;. | 
 **x_correlation_id** | **UUID**| Optional client-supplied correlation id. The service uses this in every log line and downstream call. If absent the service mints a new UUID and echoes it in the response header. | [optional] 

### Return type

[**PaginatedConversationRead**](PaginatedConversationRead.md)

### Authorization

[AgentToken](../README.md#AgentToken)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful response |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **post_turn**
> AnswerResponse post_turn(conversation_id, x_agent_token, conversation_turn_request, x_correlation_id=x_correlation_id, idempotency_key=idempotency_key)

Run a drill-down turn through the full query pipeline.

Two scopes are required at the agent layer:
``flyquery.conversations:write`` (this is a mutating turn
write) and the underlying ``flyquery.query:read`` (the pipeline
executes a query). We verify the conversations scope here and
delegate the query-tier check to the pipeline's scope guard.

Replay-dedup'd via ``Idempotency-Key`` (required) -- the
4-agent pipeline is the costliest endpoint in the API.

### Example

* Api Key Authentication (AgentToken):

```python
import flyquery_sdk
from flyquery_sdk.models.answer_response import AnswerResponse
from flyquery_sdk.models.conversation_turn_request import ConversationTurnRequest
from flyquery_sdk.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = flyquery_sdk.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure API key authorization: AgentToken
configuration.api_key['AgentToken'] = os.environ["API_KEY"]

# Uncomment below to setup prefix (e.g. Bearer) for API key, if needed
# configuration.api_key_prefix['AgentToken'] = 'Bearer'

# Enter a context with an instance of the API client
async with flyquery_sdk.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = flyquery_sdk.AgentConversationsApi(api_client)
    conversation_id = 'conversation_id_example' # str | 
    x_agent_token = 'fqt_live_aBcDeF1234567890aBcDeF1234567890' # str | Machine-to-machine bearer token. Replaces X-Tenant-Id and X-Workspace-Id on agent-tier endpoints -- the token's claims encode the tenant + workspace + scopes. Issue via ``POST /api/v1/agent-tokens``.
    conversation_turn_request = flyquery_sdk.ConversationTurnRequest() # ConversationTurnRequest | 
    x_correlation_id = UUID('550e8400-e29b-41d4-a716-446655440000') # UUID | Optional client-supplied correlation id. The service uses this in every log line and downstream call. If absent the service mints a new UUID and echoes it in the response header. (optional)
    idempotency_key = 'ingest-2026-05-23-abc123' # str | Optional client-supplied idempotency key for mutating operations. The first request with a key persists its result; subsequent requests with the same key + same tenant return the cached response. Keys expire after 24h. (optional)

    try:
        # Run a drill-down turn through the full query pipeline.
        api_response = await api_instance.post_turn(conversation_id, x_agent_token, conversation_turn_request, x_correlation_id=x_correlation_id, idempotency_key=idempotency_key)
        print("The response of AgentConversationsApi->post_turn:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling AgentConversationsApi->post_turn: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **conversation_id** | **str**|  | 
 **x_agent_token** | **str**| Machine-to-machine bearer token. Replaces X-Tenant-Id and X-Workspace-Id on agent-tier endpoints -- the token&#39;s claims encode the tenant + workspace + scopes. Issue via &#x60;&#x60;POST /api/v1/agent-tokens&#x60;&#x60;. | 
 **conversation_turn_request** | [**ConversationTurnRequest**](ConversationTurnRequest.md)|  | 
 **x_correlation_id** | **UUID**| Optional client-supplied correlation id. The service uses this in every log line and downstream call. If absent the service mints a new UUID and echoes it in the response header. | [optional] 
 **idempotency_key** | **str**| Optional client-supplied idempotency key for mutating operations. The first request with a key persists its result; subsequent requests with the same key + same tenant return the cached response. Keys expire after 24h. | [optional] 

### Return type

[**AnswerResponse**](AnswerResponse.md)

### Authorization

[AgentToken](../README.md#AgentToken)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **read**
> ConversationRead read(conversation_id, x_agent_token, x_correlation_id=x_correlation_id)

Fetch a conversation with its turns.

### Example

* Api Key Authentication (AgentToken):

```python
import flyquery_sdk
from flyquery_sdk.models.conversation_read import ConversationRead
from flyquery_sdk.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = flyquery_sdk.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure API key authorization: AgentToken
configuration.api_key['AgentToken'] = os.environ["API_KEY"]

# Uncomment below to setup prefix (e.g. Bearer) for API key, if needed
# configuration.api_key_prefix['AgentToken'] = 'Bearer'

# Enter a context with an instance of the API client
async with flyquery_sdk.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = flyquery_sdk.AgentConversationsApi(api_client)
    conversation_id = 'conversation_id_example' # str | 
    x_agent_token = 'fqt_live_aBcDeF1234567890aBcDeF1234567890' # str | Machine-to-machine bearer token. Replaces X-Tenant-Id and X-Workspace-Id on agent-tier endpoints -- the token's claims encode the tenant + workspace + scopes. Issue via ``POST /api/v1/agent-tokens``.
    x_correlation_id = UUID('550e8400-e29b-41d4-a716-446655440000') # UUID | Optional client-supplied correlation id. The service uses this in every log line and downstream call. If absent the service mints a new UUID and echoes it in the response header. (optional)

    try:
        # Fetch a conversation with its turns.
        api_response = await api_instance.read(conversation_id, x_agent_token, x_correlation_id=x_correlation_id)
        print("The response of AgentConversationsApi->read:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling AgentConversationsApi->read: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **conversation_id** | **str**|  | 
 **x_agent_token** | **str**| Machine-to-machine bearer token. Replaces X-Tenant-Id and X-Workspace-Id on agent-tier endpoints -- the token&#39;s claims encode the tenant + workspace + scopes. Issue via &#x60;&#x60;POST /api/v1/agent-tokens&#x60;&#x60;. | 
 **x_correlation_id** | **UUID**| Optional client-supplied correlation id. The service uses this in every log line and downstream call. If absent the service mints a new UUID and echoes it in the response header. | [optional] 

### Return type

[**ConversationRead**](ConversationRead.md)

### Authorization

[AgentToken](../README.md#AgentToken)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful response |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

