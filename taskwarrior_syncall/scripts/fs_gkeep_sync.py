import os
from typing import Sequence

import click
from bubop import (
    check_optional_mutually_exclusive,
    format_dict,
    log_to_syslog,
    logger,
    loguru_tqdm_sink,
)

from taskwarrior_syncall import inform_about_app_extras

try:
    from taskwarrior_syncall import GKeepNoteSide
except ImportError:
    inform_about_app_extras(["gkeepapi"])

from taskwarrior_syncall import (
    Aggregator,
    FilesystemSide,
    __version__,
    cache_or_reuse_cached_combination,
    convert_fs_file_to_gkeep_note,
    convert_gkeep_note_to_fs_file,
    fetch_app_configuration,
    fetch_from_pass_manager,
    get_resolution_strategy,
    inform_about_combination_name_usage,
    list_named_combinations,
    opt_combination,
    opt_custom_combination_savename,
    opt_filesystem_root,
    opt_gkeep_labels,
    opt_gkeep_passwd_pass_path,
    opt_gkeep_user_pass_path,
    opt_list_combinations,
    opt_resolution_strategy,
    report_toplevel_exception,
)


@click.command()
# google keep options -------------------------------------------------------------------------
@opt_gkeep_labels()
@opt_gkeep_user_pass_path()
@opt_gkeep_passwd_pass_path()
# filesystem options --------------------------------------------------------------------------
@opt_filesystem_root()
# misc options --------------------------------------------------------------------------------
@opt_list_combinations("Filesystem", "Google Keep")
@opt_resolution_strategy()
@opt_combination("Filesystem", "Google Keep")
@opt_custom_combination_savename("Filesystem", "Google Keep")
@click.option("-v", "--verbose", count=True)
@click.version_option(__version__)
def main(
    filesystem_root: str,
    gkeep_labels: Sequence[str],
    gkeep_user_pass_path: str,
    gkeep_passwd_pass_path: str,
    resolution_strategy: str,
    verbose: int,
    combination_name: str,
    custom_combination_savename: str,
    do_list_combinations: bool,
):
    """
    Synchronize Notes and Lists from your Google Keep a list of files on your local filesystem.

    You can only synchronize a subset of your Google Keep notes based on a set of provided
    labels and you can specify where to create the files by specifying the path to a local
    directory. If you don't specify Google Keep Labels it will synchronize all your Google Keep
    notes.

    For each Google Keep Note or List, fs_gkeep_sync will create a corresponding file under the
    specified root directory with a matching name. Any addition, deletion and modification of
    the files on the filesystem will result in the corresponding addition, deletion and
    modification of the corresponding Google Keep item. The same holds the other way around.
    """
    # setup logger ----------------------------------------------------------------------------
    loguru_tqdm_sink(verbosity=verbose)
    log_to_syslog(name="fs_gkeep_sync")
    logger.debug("Initialising...")
    inform_about_config = False

    if do_list_combinations:
        list_named_combinations(config_fname="fs_gkeep_configs")
        return 0

    # cli validation --------------------------------------------------------------------------
    check_optional_mutually_exclusive(combination_name, custom_combination_savename)
    combination_of_filesystem_root_and_gkeep_labels = any(
        [
            filesystem_root,
            gkeep_labels,
        ]
    )
    check_optional_mutually_exclusive(
        combination_name, combination_of_filesystem_root_and_gkeep_labels
    )

    # existing combination name is provided ---------------------------------------------------
    if combination_name is not None:
        app_config = fetch_app_configuration(
            config_fname="fs_gkeep_configs", combination=combination_name
        )
        filesystem_root = app_config["filesystem_root"]
        gkeep_labels = app_config["gkeep_labels"]

    # combination manually specified ----------------------------------------------------------
    else:
        inform_about_config = True
        combination_name = cache_or_reuse_cached_combination(
            config_args={
                "filesystem_root": filesystem_root,
                "gkeep_labels": gkeep_labels,
            },
            config_fname="fs_gkeep_configs",
            custom_combination_savename=custom_combination_savename,
        )

    # announce configuration ------------------------------------------------------------------
    logger.info(
        format_dict(
            header="Configuration",
            items={
                "Filesystem Root": filesystem_root,
                "Google Keep Note": gkeep_labels,
            },
            prefix="\n\n",
            suffix="\n",
        )
    )

    # initialize sides ------------------------------------------------------------------------
    # fetch username
    gkeep_user = os.environ.get("GKEEP_USERNAME")
    if gkeep_user is not None:
        logger.debug("Reading the gkeep username from environment variable...")
    else:
        gkeep_user = fetch_from_pass_manager(gkeep_user_pass_path)
    assert gkeep_user

    # fetch password
    gkeep_passwd = os.environ.get("GKEEP_PASSWD")
    if gkeep_passwd is not None:
        logger.debug("Reading the gkeep password from environment variable...")
    else:
        gkeep_passwd = fetch_from_pass_manager(gkeep_passwd_pass_path)
    assert gkeep_passwd

    # initialize google keep  -----------------------------------------------------------------
    gkeep_side = GKeepNoteSide(
        gkeep_labels=gkeep_labels,
        gkeep_user=gkeep_user,
        gkeep_passwd=gkeep_passwd,
    )

    # initialize Filesystem Side --------------------------------------------------------------
    filesystem_side = FilesystemSide(filesystem_root=filesystem_root)

    # sync ------------------------------------------------------------------------------------
    try:
        with Aggregator(
            side_A=gkeep_side,
            side_B=filesystem_side,
            converter_B_to_A=convert_fs_file_to_gkeep_note,
            converter_A_to_B=convert_gkeep_note_to_fs_file,
            resolution_strategy=get_resolution_strategy(
                resolution_strategy,
                side_A_type=type(gkeep_side),
                side_B_type=type(filesystem_side),
            ),
            config_fname=combination_name,
            ignore_keys=(
                (),
                ("due", "end", "entry", "modified", "urgency"),
            ),
        ) as aggregator:
            aggregator.sync()
    except KeyboardInterrupt:
        logger.error("Exiting...")
        return 1
    except:
        report_toplevel_exception(is_verbose=verbose >= 1)
        return 1

    if inform_about_config:
        inform_about_combination_name_usage(combination_name)

    return 0


if __name__ == "__main__":
    main()
