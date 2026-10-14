from app.core.polish_counts import (
    format_game_count,
    format_in_stores,
    format_store_count,
    format_store_count_locative,
)
from app.core.store_classification import StoreClass, classify_store, store_class_label_pl


def test_store_count_declension():
    assert format_store_count(1) == "1 sklep"
    assert format_store_count(2) == "2 sklepy"
    assert format_store_count(4) == "4 sklepy"
    assert format_store_count(5) == "5 sklepów"
    assert format_store_count(10) == "10 sklepów"
    assert format_store_count(12) == "12 sklepów"
    assert format_store_count(22) == "22 sklepy"


def test_store_count_locative():
    assert format_store_count_locative(1) == "1 sklepie"
    assert format_store_count_locative(10) == "10 sklepach"
    assert format_in_stores(10) == "w 10 sklepach"


def test_game_count_declension():
    assert format_game_count(1) == "1 gra"
    assert format_game_count(3) == "3 gry"
    assert format_game_count(11) == "11 gier"


def test_store_taxonomy_known_shops():
    assert classify_store("Steam") is StoreClass.OFFICIAL_STORE
    assert classify_store("GOG") is StoreClass.OFFICIAL_STORE
    assert classify_store("Epic Games") is StoreClass.OFFICIAL_STORE
    assert classify_store("Fanatical") is StoreClass.AUTHORIZED_RESELLER
    assert classify_store("Instant Gaming") is StoreClass.AUTHORIZED_RESELLER
    assert classify_store("Green Man Gaming") is StoreClass.AUTHORIZED_RESELLER
    assert classify_store("Humble") is StoreClass.AUTHORIZED_RESELLER
    assert classify_store("G2A") is StoreClass.MARKETPLACE
    assert classify_store("Kinguin") is StoreClass.MARKETPLACE
    assert classify_store("Gamivo") is StoreClass.MARKETPLACE
    assert classify_store("Eneba") is StoreClass.MARKETPLACE
    assert classify_store("CDKeys") is StoreClass.MARKETPLACE
    assert store_class_label_pl(StoreClass.AUTHORIZED_RESELLER) == "Autoryzowany sprzedawca"
