from common.schemas.pagination import DEFAULT_PER_PAGE, MAX_PER_PAGE, PageRequest, page_request


def test_default_page_is_ten_for_any_list():
    window = page_request()
    assert window.page == 1
    assert window.per_page == DEFAULT_PER_PAGE == 10
    assert PageRequest().per_page == 10


def test_an_asked_count_replaces_the_page_size_and_stays_capped():
    assert page_request(per_page=25).per_page == 25
    assert page_request(per_page=500).per_page == MAX_PER_PAGE
