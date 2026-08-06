import jupiter_data_transform.main as main_module


def test_configure_event_loop_policy_uses_selector_on_windows(monkeypatch) -> None:
    policy = object()
    selected: list[object] = []

    monkeypatch.setattr(main_module.sys, "platform", "win32")
    monkeypatch.setattr(
        main_module.asyncio,
        "WindowsSelectorEventLoopPolicy",
        lambda: policy,
        raising=False,
    )
    monkeypatch.setattr(main_module.asyncio, "set_event_loop_policy", selected.append)

    main_module.configure_event_loop_policy()

    assert selected == [policy]


def test_configure_event_loop_policy_is_noop_outside_windows(monkeypatch) -> None:
    selected: list[object] = []

    monkeypatch.setattr(main_module.sys, "platform", "linux")
    monkeypatch.setattr(main_module.asyncio, "set_event_loop_policy", selected.append)

    main_module.configure_event_loop_policy()

    assert selected == []
