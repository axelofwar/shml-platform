"""Ray orchestration wrapper — core logic in libs.evaluation.adversarial.adversarial_validator."""
import ray


@ray.remote(num_cpus=2, num_gpus=0.5)
def validate_adversarial(config: dict) -> dict:
    """Distributed Ray task: adversarial robustness validation."""
    from libs.evaluation.adversarial.adversarial_validator import AdversarialValidator, AdversarialConfig
    val_config = AdversarialConfig(**config)
    validator = AdversarialValidator(val_config)
    return validator.run()


if __name__ == "__main__":
    from libs.evaluation.adversarial.adversarial_validator import main
    main()
