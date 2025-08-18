from .strangle import StrangleStrategy

if __name__ == "__main__":
    """
    This is the main entry point to run the Strangle strategy.

    It initializes the strategy and starts its main execution loop.
    The script should be run from the root of the project, for example:
    `python -m option_strategy.strangle.run_strangle`
    """
    try:
        # The strategy name provided here must match the folder name
        # and the name used in config/state/log/trade files.
        strategy = StrangleStrategy(strategy_name="strangle")
        strategy.run()
    except Exception as e:
        print(f"A critical error occurred: {e}")
        # In a real production environment, you might want to log this
        # to a global error log or send a notification.