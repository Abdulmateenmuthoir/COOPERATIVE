"""
Standard pagination for the Cooperative Management SaaS Platform.
"""
from rest_framework.pagination import PageNumberPagination


class StandardResultsPagination(PageNumberPagination):
    """
    Default pagination for all list endpoints.
    Clients can control page size up to a maximum of 100.
    """

    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 100
    page_query_param = "page"


class LargeResultsPagination(PageNumberPagination):
    """
    Pagination for endpoints that may return larger datasets,
    such as financial ledger entries or audit logs.
    """

    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 500


class SmallResultsPagination(PageNumberPagination):
    """
    Pagination for endpoints with typically small result sets,
    such as notification lists or committee members.
    """

    page_size = 10
    page_size_query_param = "page_size"
    max_page_size = 50
