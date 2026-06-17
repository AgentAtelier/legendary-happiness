from devforge.simulation.preview.controller import PreviewController


def main():

    preview = PreviewController()

    # Example generated system
    generated_system = {
        "name": "weather",
        "config": {
            "rain_variation": 0.1
        },
        "logic": {
            "rules": [
                {
                    "type": "environment_delta",
                    "target": "rain",
                    "delta": 0.02
                }
            ]
        }
    }

    preview.add_generated_system(generated_system)

    preview.run(steps=100)

    print("World snapshot:")
    print(preview.snapshot())

    print("\nMetrics:")
    print(preview.metrics())

    print("\nParameters:")
    print(preview.parameters())


if __name__ == "__main__":
    main()