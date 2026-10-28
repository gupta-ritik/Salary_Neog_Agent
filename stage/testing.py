
from complete_stage6 import compute_result_score


def make_state(final_offer, status="accepted"):
    return {
        "opening_offer": 14.4,
        "budget_ceiling": 20.0,
        "final_offer": final_offer,
        "status": status,
    }


tests = [
    ("Accept opening offer", make_state(14.4), 0.0),
    ("Improved offer", make_state(15.5), 7.9),
    ("Reach budget ceiling", make_state(20.0), 40.0),
    ("Walk away", make_state(None, "walked_away"), 0.0),
    ("Timeout", make_state(None, "timeout"), 0.0),
]

for name, state, expected in tests:
    actual = compute_result_score(state)
    assert actual == expected, (
        f"{name}: expected {expected}, got {actual}"
    )
    print(f"PASS: {name}")

for invalid_offer in (25.0, 12.0):
    try:
        compute_result_score(make_state(invalid_offer))
    except ValueError:
        print(f"PASS: Invalid offer {invalid_offer} rejected")
    else:
        raise AssertionError(
            f"Invalid offer {invalid_offer} was not rejected"
        )

print("\nAll scoring tests passed!")
