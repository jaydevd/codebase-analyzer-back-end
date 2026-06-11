from rest_framework import serializers

class PromptSeriallizer(serializers.Serializer):
  repo_full_name=serializers.CharField(required=True, allow_blank=False)
  branch=serializers.JSONField(required=True, allow_blank=False)
  prompt=serializers.CharField(required=True, allow_blank=False)
