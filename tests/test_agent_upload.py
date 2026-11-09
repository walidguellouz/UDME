from argparse import Namespace
from unittest.mock import patch

from udme_agent import cli


def test_gui_command_surfaces_enrollment_errors():
    args = Namespace(gui=True, f=lambda _: (_ for _ in ()).throw(SystemExit("Jeton invalide ou expiré.")))
    with patch.object(cli, "_show_upload_result") as show:
        cli.run_command(args)
    show.assert_called_once_with("Jeton invalide ou expiré.", gui=True)


def test_console_command_preserves_exit_behavior():
    args = Namespace(gui=False, f=lambda _: (_ for _ in ()).throw(SystemExit("Jeton invalide ou expiré.")))
    try:
        cli.run_command(args)
    except SystemExit as exc:
        assert exc.code == "Jeton invalide ou expiré."
    else:
        raise AssertionError("CLI failures must keep their exit status.")


def _args():
    return Namespace(
        gui=False,
        root=["C:\\data"],
        include_noise=False,
        include_removable=False,
        max_minutes=1,
        json=False,
        upload=True,
        server=cli.DEFAULT_SERVER,
        out="udme_out",
        product_hint=None,
    )


def test_find_database_enrolls_and_requests_upload():
    with (
        patch.object(cli, "find_databases", return_value=[object()]),
        patch.object(cli.picker, "choose", return_value="C:\\data\\store.db"),
        patch.object(cli, "_ensure_enrolled") as enroll,
        patch.object(cli.picker, "proceed") as proceed,
        patch.object(cli, "cmd_scan") as scan,
    ):
        cli.cmd_find(_args())
        enroll.assert_called_once_with(cli.DEFAULT_SERVER, gui=False)
        proceed.call_args.kwargs["run_scan"]()
        assert scan.call_args.args[0].upload == "auto"
        assert scan.call_args.args[0].gui is False


def test_sql_dump_does_not_consume_enrollment_token():
    with (
        patch.object(cli, "find_databases", return_value=[object()]),
        patch.object(cli.picker, "choose", return_value="C:\\data\\backup.sql"),
        patch.object(cli, "_ensure_enrolled") as enroll,
        patch.object(cli.picker, "proceed") as proceed,
    ):
        cli.cmd_find(_args())
        enroll.assert_not_called()
        proceed.assert_called_once_with("C:\\data\\backup.sql")
