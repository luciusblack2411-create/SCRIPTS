from cisco_assessment.models import (
    AssessmentRun,
    CommandExecution,
    Device,
    PlatformFamily,
    RawCommandOutput,
)


def test_models_round_trip_through_json_and_keep_traceability_chain() -> None:
    device = Device(
        management_address="10.10.10.20",
        hostname="SW-CORE-01",
        platform_family=PlatformFamily.IOS_XE,
    )
    run = AssessmentRun(
        device_id=device.id,
        framework_version="0.1.0",
        target_snapshot=device.snapshot(),
        command_catalog_version="0.1",
        ruleset_version="0.1",
    )
    execution = CommandExecution(
        assessment_run_id=run.id,
        command_key="system.version",
        command="show version",
        sequence=1,
    )
    raw = RawCommandOutput.from_text(
        command_execution_id=execution.id,
        content="Cisco IOS XE Software, Version 17.12.4\n",
    )

    restored_device = Device.model_validate_json(device.model_dump_json())
    restored_run = AssessmentRun.model_validate_json(run.model_dump_json())
    restored_execution = CommandExecution.model_validate_json(execution.model_dump_json())
    restored_raw = RawCommandOutput.model_validate_json(raw.model_dump_json())

    assert restored_run.device_id == restored_device.id
    assert restored_execution.assessment_run_id == restored_run.id
    assert restored_raw.command_execution_id == restored_execution.id
    assert restored_raw.content == raw.content
    assert restored_raw.sha256 == raw.sha256
