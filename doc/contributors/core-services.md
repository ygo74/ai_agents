# Shared core services and model providers

`ai_agent_lab.core` contains the settings and helpers shared by the applications:
chat provider selection, Azure credential creation, and logging setup. It does
not depend on either agent framework. Framework-specific client construction
stays in the MAF and LangGraph adapter distributions.

## Model client construction

```mermaid
classDiagram
    class ChatProvider
    class AzureCredentialMode
    class AzureIdentityCredentialProvider
    class ConfiguredChatClientFactory
    class MafChatClientFactory
    class LangGraphChatModelFactory
    class OpenAIChatClient
    class ChatOpenAI
    class AzureChatOpenAI
    ConfiguredChatClientFactory --> ChatProvider : selects provider
    ConfiguredChatClientFactory --> MafChatClientFactory : builds Mail client
    MafChatClientFactory --> OpenAIChatClient : builds native client
    LangGraphChatModelFactory --> ChatOpenAI : builds OpenAI model
    LangGraphChatModelFactory --> AzureChatOpenAI : builds Azure model
    ConfiguredChatClientFactory --> AzureIdentityCredentialProvider : requests Entra credential
    AzureIdentityCredentialProvider --> AzureCredentialMode : selects credential mode
```

```mermaid
sequenceDiagram
    participant Mail as ConfiguredChatClientFactory
    participant MAF as MafChatClientFactory
    participant Wiki as build_chat_model
    participant Entra as AzureIdentityCredentialProvider
    participant LG as LangGraphChatModelFactory
    participant Provider as Native provider client
    alt Mail uses OpenAI
        Mail->>MAF: openai(model)
        MAF->>Provider: create OpenAIChatClient
    else Mail uses Azure OpenAI
        Mail->>Entra: create credential mode
        Entra-->>Mail: TokenCredential or None
        Mail->>MAF: azure_openai(route, credential)
        MAF->>Provider: create routed OpenAIChatClient
    end
    alt Wiki uses OpenAI
        Wiki->>LG: openai(model)
        LG->>Provider: create ChatOpenAI
    else Wiki uses Azure OpenAI
        Wiki->>Entra: create_or_none for credential mode
    Entra-->>Wiki: credential or None for API key
        Wiki->>LG: azure_openai(route, credential)
        LG->>Provider: create AzureChatOpenAI
    end
    Provider-->>Mail: SupportsChatGetResponse
    Provider-->>Wiki: BaseChatModel
```

Both applications support OpenAI and Azure OpenAI. API key mode leaves key
resolution to the framework client. Entra modes use `AzureIdentityCredentialProvider`;
the credential object is passed to the native client and its token is not
handled by application code. The `azure-identity` import is deferred so an
OpenAI or API-key deployment does not require that optional package.

The Mail composition uses `ConfiguredChatClientFactory`. Wiki constructs its
model in `build_chat_model()` using `LangGraphChatModelFactory`. Keep their
provider settings aligned, and keep secrets out of settings models and logs.

## Logging

`setup_logging()` configures application loggers in `ai_agent_lab.core` and
updates existing handlers when the host configured them first. A host may
provide handlers and a default level. Do not add provider payloads or
credentials to startup logs.

Sources: [`agents/core`](../../agents/core/),
[`Mail chat client composition`](../../agents/mail/src/ai_agent_lab/mail/bootstrap/chat_client.py),
[`Wiki chat model construction`](../../agents/wiki/src/ai_agent_lab/wiki/adapters/cli/entrypoint.py),
and [MAF client factory](../../agents/maf/src/ai_agent_lab/maf/chat_client.py).
Tests: [chat client selection](../../tests/integration/test_chat_client_selection.py)
and [logging configuration](../../tests/unit/test_logging_config.py).

See the [configuration guide](../../docs/configuration.md) and [system
specification](../../spec/README.md).
