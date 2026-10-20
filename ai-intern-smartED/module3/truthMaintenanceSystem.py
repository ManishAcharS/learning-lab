# Knowledge base (initial beliefs)
beliefs = {
    "sky_is_clear": True,
    "it_will_rain": False
}

# Rule: if sky is not clear, it will rain
def update_belief():
    if beliefs["sky_is_clear"]:
        beliefs["it_will_rain"] = False
    else:
        beliefs["it_will_rain"] = True

print("Before:", beliefs)

# Change a fact, then re-run the dependency rule
beliefs["sky_is_clear"] = False
update_belief()

print("After:", beliefs)
