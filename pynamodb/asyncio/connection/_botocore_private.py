"""
Type-annotates the private aiobotocore APIs that we're currently relying on.
"""
from typing import Dict

import botocore.credentials
import botocore.endpoint
import botocore.hooks
import botocore.signers
from aiobotocore.client import AioBaseClient


class BotocoreEndpointPrivate(botocore.endpoint.Endpoint):
    _event_emitter: botocore.hooks.HierarchicalEmitter


class BotocoreRequestSignerPrivate(botocore.signers.RequestSigner):
    _credentials: botocore.credentials.Credentials


class BotocoreBaseClientPrivate(AioBaseClient):
    _endpoint: BotocoreEndpointPrivate
    _request_signer: BotocoreRequestSignerPrivate

    async def _make_api_call(        self,
        operation_name: str,
        operation_kwargs: Dict,
    ) -> Dict:
        raise NotImplementedError
