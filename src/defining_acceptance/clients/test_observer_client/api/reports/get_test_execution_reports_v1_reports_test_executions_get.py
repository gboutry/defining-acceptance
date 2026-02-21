import datetime
from http import HTTPStatus
from typing import Any, cast

import httpx
from dateutil.parser import isoparse

from ... import errors
from ...client import AuthenticatedClient, Client
from ...models.http_validation_error import HTTPValidationError
from ...types import UNSET, Response, Unset


def _get_kwargs(
    *,
    start_date: datetime.datetime | Unset = isoparse("0001-01-01T00:00:00"),
    end_date: datetime.datetime | None | Unset = UNSET,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    json_start_date: str | Unset = UNSET
    if not isinstance(start_date, Unset):
        json_start_date = start_date.isoformat()
    params["start_date"] = json_start_date

    json_end_date: None | str | Unset
    if isinstance(end_date, Unset):
        json_end_date = UNSET
    elif isinstance(end_date, datetime.datetime):
        json_end_date = end_date.isoformat()
    else:
        json_end_date = end_date
    params["end_date"] = json_end_date

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/v1/reports/test-executions",
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Any | HTTPValidationError | None:
    if response.status_code == 200:
        response_200 = cast(Any, None)
        return response_200

    if response.status_code == 422:
        response_422 = HTTPValidationError.from_dict(response.json())

        return response_422

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[Any | HTTPValidationError]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient | Client,
    start_date: datetime.datetime | Unset = isoparse("0001-01-01T00:00:00"),
    end_date: datetime.datetime | None | Unset = UNSET,
) -> Response[Any | HTTPValidationError]:
    """Get Test Execution Reports

     Returns a csv report detailing all test executions within a given date range.
    Together with their artefact and environment details in csv format.

    Args:
        start_date (datetime.datetime | Unset):  Default: isoparse('0001-01-01T00:00:00').
        end_date (datetime.datetime | None | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        start_date=start_date,
        end_date=end_date,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient | Client,
    start_date: datetime.datetime | Unset = isoparse("0001-01-01T00:00:00"),
    end_date: datetime.datetime | None | Unset = UNSET,
) -> Any | HTTPValidationError | None:
    """Get Test Execution Reports

     Returns a csv report detailing all test executions within a given date range.
    Together with their artefact and environment details in csv format.

    Args:
        start_date (datetime.datetime | Unset):  Default: isoparse('0001-01-01T00:00:00').
        end_date (datetime.datetime | None | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | HTTPValidationError
    """

    return sync_detailed(
        client=client,
        start_date=start_date,
        end_date=end_date,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient | Client,
    start_date: datetime.datetime | Unset = isoparse("0001-01-01T00:00:00"),
    end_date: datetime.datetime | None | Unset = UNSET,
) -> Response[Any | HTTPValidationError]:
    """Get Test Execution Reports

     Returns a csv report detailing all test executions within a given date range.
    Together with their artefact and environment details in csv format.

    Args:
        start_date (datetime.datetime | Unset):  Default: isoparse('0001-01-01T00:00:00').
        end_date (datetime.datetime | None | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | HTTPValidationError]
    """

    kwargs = _get_kwargs(
        start_date=start_date,
        end_date=end_date,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient | Client,
    start_date: datetime.datetime | Unset = isoparse("0001-01-01T00:00:00"),
    end_date: datetime.datetime | None | Unset = UNSET,
) -> Any | HTTPValidationError | None:
    """Get Test Execution Reports

     Returns a csv report detailing all test executions within a given date range.
    Together with their artefact and environment details in csv format.

    Args:
        start_date (datetime.datetime | Unset):  Default: isoparse('0001-01-01T00:00:00').
        end_date (datetime.datetime | None | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | HTTPValidationError
    """

    return (
        await asyncio_detailed(
            client=client,
            start_date=start_date,
            end_date=end_date,
        )
    ).parsed
