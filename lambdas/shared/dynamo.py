"""DynamoDB client helpers."""

import os

import boto3
from boto3.dynamodb.conditions import Key

TABLE_NAME = os.environ.get("TABLE_NAME", "victorymail")

_table = None


def _get_table():
    global _table
    if _table is None:
        dynamodb = boto3.resource("dynamodb")
        _table = dynamodb.Table(TABLE_NAME)
    return _table


def get_item(pk: str, sk: str) -> dict | None:
    """Get a single item by primary key. Returns None if not found."""
    resp = _get_table().get_item(Key={"PK": pk, "SK": sk})
    return resp.get("Item")


def put_item(item: dict) -> None:
    """Put an item into the table."""
    _get_table().put_item(Item=item)


def update_item(pk: str, sk: str, updates: dict) -> dict:
    """Update item attributes. Returns the full item (ALL_NEW)."""
    expr_parts = []
    names = {}
    values = {}
    for i, (key, value) in enumerate(updates.items()):
        alias = f"#k{i}"
        val_alias = f":v{i}"
        expr_parts.append(f"{alias} = {val_alias}")
        names[alias] = key
        values[val_alias] = value

    resp = _get_table().update_item(
        Key={"PK": pk, "SK": sk},
        UpdateExpression="SET " + ", ".join(expr_parts),
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=values,
        ReturnValues="ALL_NEW",
    )
    return resp["Attributes"]


def delete_item(pk: str, sk: str) -> None:
    """Delete an item by primary key."""
    _get_table().delete_item(Key={"PK": pk, "SK": sk})


def query(
    pk: str,
    sk_prefix: str | None = None,
    index_name: str | None = None,
    limit: int = 25,
    ascending: bool = True,
    exclusive_start_key: dict | None = None,
) -> tuple[list[dict], dict | None]:
    """Query the table or a GSI by PK and optional SK prefix.

    Returns (items, last_evaluated_key).
    """
    pk_attr = "PK"
    sk_attr = "SK"
    if index_name:
        # e.g. "GSI1" -> "GSI1PK", "GSI1SK"
        pk_attr = f"{index_name}PK"
        sk_attr = f"{index_name}SK"

    key_condition = Key(pk_attr).eq(pk)
    if sk_prefix:
        key_condition = key_condition & Key(sk_attr).begins_with(sk_prefix)

    kwargs = {
        "KeyConditionExpression": key_condition,
        "Limit": limit,
        "ScanIndexForward": ascending,
    }
    if index_name:
        kwargs["IndexName"] = index_name
    if exclusive_start_key:
        kwargs["ExclusiveStartKey"] = exclusive_start_key

    resp = _get_table().query(**kwargs)
    return resp.get("Items", []), resp.get("LastEvaluatedKey")


def query_gsi(
    index_name: str,
    pk_value: str,
    sk_prefix: str | None = None,
    limit: int = 25,
    ascending: bool = True,
    exclusive_start_key: dict | None = None,
) -> tuple[list[dict], dict | None]:
    """Query a GSI. Builds correct key attribute names from index_name.

    index_name should be like "GSI1", "GSI2", etc.
    """
    return query(
        pk=pk_value,
        sk_prefix=sk_prefix,
        index_name=index_name,
        limit=limit,
        ascending=ascending,
        exclusive_start_key=exclusive_start_key,
    )


def transact_write(items: list[dict]) -> None:
    """Execute a DynamoDB transact_write_items call.

    Each item in the list should be a dict with one key: 'Put', 'Update',
    'Delete', or 'ConditionCheck', matching the TransactWriteItems API.
    """
    client = boto3.client("dynamodb")
    client.transact_write_items(TransactItems=items)
