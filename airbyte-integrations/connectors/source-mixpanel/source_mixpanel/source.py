#
# Copyright (c) 2022 Airbyte, Inc., all rights reserved.
#

import base64
import logging
from typing import Any, List, Mapping, Tuple

import pendulum
import requests
from airbyte_cdk.logger import AirbyteLogger
from airbyte_cdk.sources import AbstractSource
from airbyte_cdk.sources.streams import Stream
from airbyte_cdk.sources.streams.http.auth import TokenAuthenticator

from .streams import Annotations, CohortMembers, Cohorts, Engage, Export, Funnels, FunnelsList, Revenue
from .testing import adapt_streams_if_testing, adapt_validate_if_testing


class TokenAuthenticatorBase64(TokenAuthenticator):
    def __init__(self, token: str, auth_method: str = "Basic", **kwargs):
        token = base64.b64encode(token.encode("utf8")).decode("utf8")
        super().__init__(token=token, auth_method=auth_method, **kwargs)


class SourceMixpanel(AbstractSource):
    @adapt_validate_if_testing
    def _validate_and_transform(self, config: Mapping[str, Any]):
        logger = logging.getLogger("airbyte")
        source_spec = self.spec(logger)
        default_project_timezone = source_spec.connectionSpecification["properties"]["project_timezone"]["default"]
        config["project_timezone"] = pendulum.timezone(config.get("project_timezone", default_project_timezone))

        today = pendulum.today(tz=config["project_timezone"]).date()
        start_date = config.get("start_date")
        if start_date:
            config["start_date"] = pendulum.parse(start_date).date()
        else:
            config["start_date"] = today.subtract(days=365)

        end_date = config.get("end_date")
        if end_date:
            config["end_date"] = pendulum.parse(end_date).date()
        else:
            config["end_date"] = today

        for k in ["attribution_window", "select_properties_by_default", "region", "date_window_size"]:
            if k not in config:
                config[k] = source_spec.connectionSpecification["properties"][k]["default"]
        return config

    def check_connection(self, logger: AirbyteLogger, config: Mapping[str, Any]) -> Tuple[bool, any]:
        """
        See https://github.com/airbytehq/airbyte/blob/master/airbyte-integrations/connectors/source-stripe/source_stripe/source.py#L232
        for an example.

        :param config:  the user-input config object conforming to the connector's spec.json
        :param logger:  logger object
        :return Tuple[bool, any]: (True, None) if the input config can be used to connect to the API successfully, (False, error) otherwise.
        """
        config = self._validate_and_transform(config)
        try:
            auth = TokenAuthenticatorBase64(token=config["api_secret"])
            funnels = FunnelsList(authenticator=auth, **config)
            response = requests.request(
                "GET",
                url=funnels.url_base + funnels.path(),
                headers={
                    "Accept": "application/json",
                    **auth.get_auth_header(),
                },
            )

            if response.status_code != 200:
                message = response.json()
                error_message = message.get("error")
                if error_message:
                    return False, error_message
                response.raise_for_status()
        except Exception as e:
            return False, e

        return True, None

    @adapt_streams_if_testing
    def streams(self, config: Mapping[str, Any]) -> List[Stream]:
        """
        :param config: A Mapping of the user input configuration as defined in the connector spec.
        """
        config = self._validate_and_transform(config)
        logger = logging.getLogger("airbyte")
        logger.info(f"Using start_date: {config['start_date']}, end_date: {config['end_date']}")

        auth = TokenAuthenticatorBase64(token=config["api_secret"])
        return [
            Annotations(authenticator=auth, **config),
            Cohorts(authenticator=auth, **config),
            CohortMembers(authenticator=auth, **config),
            Engage(authenticator=auth, **config),
            Export(authenticator=auth, **config),
            Funnels(authenticator=auth, **config),
            Revenue(authenticator=auth, **config),
        ]
