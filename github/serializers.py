from rest_framework import serializers


class GitHubCallbackQuerySerializer(serializers.Serializer):
    state = serializers.CharField(required=True)
    installation_id = serializers.IntegerField(required=True)
    setup_action = serializers.CharField(required=False, allow_blank=True)


class DownloadRepoSerializer(serializers.Serializer):
    branch = serializers.CharField(required=False, allow_blank=True, default="main")
    repo_full_name = serializers.CharField(required=True)

class BranchListSerializer(serializers.Serializer):
    repo = serializers.CharField(required=True)


class PreviousScanSerializer(serializers.Serializer):
    commit_url = serializers.CharField()
    commit_sha = serializers.CharField()
    indexed_at = serializers.IntegerField()


class ScanReportBranchSerializer(serializers.Serializer):
    branch = serializers.CharField()
    status = serializers.CharField()
    last_indexed_at = serializers.IntegerField(allow_null=True)
    previous_scans = PreviousScanSerializer(many=True)


class ScanReportSerializer(serializers.Serializer):
    branches = ScanReportBranchSerializer(many=True)
