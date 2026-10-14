"""Splitting a round trip into the kilometres driven with the load and the empty return."""

from datetime import UTC, datetime, timedelta

from app.leg_rules import split_legs

START = datetime(2026, 10, 1, 6, 0, tzinfo=UTC)


def run(n, every=60, step=0.01, lat0=-1.0):
    """n fixes heading north, a minute apart, 1.1 km between them."""
    return [{"at": START + timedelta(seconds=i * every), "lat": lat0 + i * step, "lng": 36.0, "accuracy_m": 8} for i in range(n)]


def test_the_distance_is_shared_where_the_delivery_fell_along_the_path():
    fixes = run(21)  # 22 km in 20 minutes
    loaded, empty = split_legs(22, fixes, START + timedelta(minutes=10))
    assert loaded + empty == 22 and loaded == 11 and empty == 11


def test_a_delivery_a_quarter_of_the_way_gives_a_short_loaded_leg_and_a_long_return():
    loaded, empty = split_legs(40, run(21), START + timedelta(minutes=5))
    assert loaded == 10 and empty == 30


def test_the_odometer_distance_is_what_is_shared_not_the_gps_total():
    loaded, empty = split_legs(30, run(21), START + timedelta(minutes=10))  # the dial says 30 km, the GPS saw 22
    assert (loaded, empty) == (15, 15)


def test_a_delivery_between_two_fixes_is_placed_in_proportion_to_the_time():
    fixes = run(11, every=120)  # 11 km in 20 minutes, a fix every two minutes
    loaded, empty = split_legs(11, fixes, START + timedelta(minutes=11))  # halfway between the sixth and seventh fix
    assert (loaded, empty) == (6, 5)


def test_a_delivery_after_the_last_fix_is_all_loaded_and_before_the_first_is_all_empty():
    assert split_legs(22, run(21), START + timedelta(hours=2)) == (22, 0)
    assert split_legs(22, run(21), START - timedelta(hours=1)) == (0, 22)


def test_nothing_is_guessed_without_a_delivery_a_distance_or_enough_fixes():
    assert split_legs(22, run(21), None) is None
    assert split_legs(None, run(21), START + timedelta(minutes=10)) is None
    assert split_legs(22, run(2), START + timedelta(seconds=30)) is None  # two fixes cannot place a delivery
    assert split_legs(22, [], START) is None
    parked = [{"at": START + timedelta(minutes=i), "lat": -1.0, "lng": 36.0, "accuracy_m": 8} for i in range(10)]
    assert split_legs(22, parked, START + timedelta(minutes=5)) is None  # it never moved
