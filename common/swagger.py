from drf_spectacular.utils import OpenApiExample, OpenApiResponse, inline_serializer
from rest_framework import serializers


def _serializer_instance(serializer_or_field):
    if serializer_or_field is None:
        return serializers.JSONField(allow_null=True, required=False)
    if isinstance(serializer_or_field, serializers.BaseSerializer):
        return serializer_or_field
    if isinstance(serializer_or_field, serializers.Field):
        return serializer_or_field
    if isinstance(serializer_or_field, type):
        if issubclass(serializer_or_field, serializers.BaseSerializer):
            return serializer_or_field()
        if issubclass(serializer_or_field, serializers.Field):
            return serializer_or_field()
    return serializer_or_field


def build_success_envelope_serializer(name, data_serializer=None):
    return inline_serializer(
        name=name,
        fields={
            "status": serializers.IntegerField(),
            "data": _serializer_instance(data_serializer),
            "message": serializers.CharField(),
        },
    )


def build_error_envelope_serializer(name):
    return inline_serializer(
        name=name,
        fields={
            "status": serializers.IntegerField(),
            "data": serializers.JSONField(allow_null=True, required=False),
            "message": serializers.CharField(),
            "errors": serializers.DictField(
                child=serializers.JSONField(),
                required=False,
                allow_empty=True,
            ),
        },
    )


def build_paginated_data_serializer(name, item_serializer, extra_fields=None):
    fields = {
        "items": _serializer_instance(item_serializer),
        "pagination": inline_serializer(
            name=f"{name}Pagination",
            fields={
                "page": serializers.IntegerField(),
                "page_size": serializers.IntegerField(),
                "total_items": serializers.IntegerField(),
                "total_pages": serializers.IntegerField(),
                "has_next": serializers.BooleanField(),
                "has_previous": serializers.BooleanField(),
            },
        ),
    }
    if extra_fields:
        fields.update(extra_fields)
    return inline_serializer(name=name, fields=fields)


def build_paginated_success_envelope_serializer(name, item_serializer, extra_fields=None):
    data_serializer = build_paginated_data_serializer(
        name=f"{name}Data",
        item_serializer=item_serializer,
        extra_fields=extra_fields,
    )
    return build_success_envelope_serializer(name=name, data_serializer=data_serializer)


def openapi_example(name, value, summary, *, response_only=True, status_codes=None):
    return OpenApiExample(
        name=name,
        value=value,
        summary=summary,
        response_only=response_only,
        status_codes=status_codes or [],
    )


def response_with_examples(serializer, description, *examples):
    return OpenApiResponse(
        response=serializer,
        description=description,
        examples=list(examples),
    )
