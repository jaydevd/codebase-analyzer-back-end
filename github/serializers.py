from rest_framework import serializers


class GitHubCallbackQuerySerializer(serializers.Serializer):
    state = serializers.CharField(required=True)
    installation_id = serializers.IntegerField(required=True)
    setup_action = serializers.CharField(required=False, allow_blank=True)


class GitHubRepositorySelectionItemSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    full_name = serializers.CharField()
    name = serializers.CharField()
    private = serializers.BooleanField()


class GitHubRepositorySelectionSerializer(serializers.Serializer):
    repositories = serializers.ListSerializer(
        child=GitHubRepositorySelectionItemSerializer(),
        min_length=1,
    )
