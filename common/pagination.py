from rest_framework.pagination import PageNumberPagination


class StandardResultsSetPagination(PageNumberPagination):
    """Pagination format that nests pagination metadata under the data envelope."""

    page_size = 10
    page_size_query_param = "page_size"
    max_page_size = 100

    def get_paginated_payload(self, results):
        return {
            "items": results,
            "pagination": {
                "page": self.page.number,
                "page_size": self.get_page_size(self.request),
                "total_items": self.page.paginator.count,
                "total_pages": self.page.paginator.num_pages,
                "has_next": self.page.has_next(),
                "has_previous": self.page.has_previous(),
            },
        }
