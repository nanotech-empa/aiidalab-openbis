#   Copyright ETH 2023 - 2024 Zürich, Scientific IT Services
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.
#
import sys

sys.path.append("/home/jovyan/aiida-openbis/")
import os
from pybis import Openbis, ImagingControl
import pybis.imaging as imaging
import numpy as np
from nanonis_importer.spmpy import Spm as spm
from datetime import datetime
import shutil
from collections import defaultdict
from src import utils
import logging

SXM_ADAPTOR = (
    "ch.ethz.sis.openbis.generic.server.dss.plugins.imaging.adaptor.NanonisSxmAdaptor"
)
DAT_ADAPTOR = (
    "ch.ethz.sis.openbis.generic.server.dss.plugins.imaging.adaptor.NanonisDatAdaptor"
)
VERBOSE = False
DEFAULT_URL = "local.openbis.ch"

logger = logging.getLogger(__name__)
logging.basicConfig(
    filename="logs/aiidalab_openbis_interface.log",
    encoding="utf-8",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s",
)


def get_instance(url=None, user=None, pw=None, token=None):
    if url is None:
        url = DEFAULT_URL

    openbis_instance = Openbis(
        url=url,
        verify_certificates=False,
        allow_http_but_do_not_use_this_in_production_and_only_within_safe_networks=True,
    )

    if token is None:
        token = openbis_instance.login(user, pw)
    else:
        openbis_instance.token = token

    return openbis_instance


def get_color_scale_range(img, channel):
    minimum = np.nanmin(img.get_channel(channel)[0])
    maximum = np.nanmax(img.get_channel(channel)[0])

    step = abs(round((maximum - minimum) / 100, 2))
    if step >= 1:
        step = 1
    elif step > 0:
        step = 0.01
    else:
        step = abs((maximum - minimum) / 100)
        step = np.log10(step)
        if np.isnan(step) or np.isinf(step):
            step = 0.01
        else:
            step = 10 ** np.floor(step)

    return [str(minimum), str(maximum), str(step)]


def _min_max_step(channel, data):
    minimum, maximum = [], []
    for spec in data:
        channel_data = spec.get_channel(channel)[0]
        minimum += [np.nanmin(channel_data)]
        maximum += [np.nanmax(channel_data)]

    minimum = np.nanmin(minimum)
    maximum = np.nanmax(maximum)

    step = abs((maximum - minimum) / 100)
    if step >= 1:
        step = 1
    elif step > 0:
        step = 0.01
    else:
        step = np.log10(step)
        if np.isnan(step) or np.isinf(step):
            step = 0.01
        else:
            step = 10 ** np.floor(step)

    return [str(minimum), str(maximum), str(step)]


def create_preview(
    openbis,
    perm_id,
    config,
    preview_format="png",
    image_index=0,
    filterConfig=[],
    tags=[],
):
    imaging_control = ImagingControl(openbis)
    preview = imaging.ImagingDataSetPreview(
        preview_format, config=config, filterConfig=filterConfig, tags=tags
    )
    preview = imaging_control.make_preview(perm_id, image_index, preview)
    return preview


def update_image_with_preview(
    openbis, perm_id, image_id, preview: imaging.ImagingDataSetPreview
):
    imaging_control = ImagingControl(openbis)
    config = imaging_control.get_property_config(perm_id)
    image = config.images[image_id]
    if len(image.previews) > preview.index:
        image.previews[preview.index] = preview
    else:
        preview.index = len(image.previews)
        image.add_preview(preview)

    imaging_control.update_property_config(perm_id, config)


def export_image(
    openbis: Openbis,
    perm_id: str,
    image_id: int,
    path_to_download: str,
    include=None,
    image_format="original",
    archive_format="zip",
    resolution="original",
):
    if include is None:
        include = ["IMAGE", "RAW_DATA"]
    imaging_control = ImagingControl(openbis)
    export_config = {
        "include": include,
        "image_format": image_format,
        "archive_format": archive_format,
        "resolution": resolution,
    }
    imaging_control.export_image(perm_id, image_id, path_to_download, **export_config)


def multi_export_images(
    openbis: Openbis,
    perm_ids: list[str],
    image_ids: list[int],
    preview_ids: list[int],
    path_to_download: str,
    include=None,
    image_format="original",
    archive_format="zip",
    resolution="original",
):
    if include is None:
        include = ["IMAGE", "RAW_DATA"]
    imaging_control = ImagingControl(openbis)
    export_config = {
        "include": include,
        "image_format": image_format,
        "archive_format": archive_format,
        "resolution": resolution,
    }

    imaging_control.export_previews(
        perm_ids, image_ids, preview_ids, path_to_download, **export_config
    )


def demo_sxm_flow(session, file_path, experiment=None, sample=None):
    dataset_sxm = create_sxm_dataset(
        session=session,
        sample=sample,
        experiment=experiment,
        file_path=file_path,
        dataset_type="IMAGING_DATA",
    )

    perm_id = dataset_sxm.permId
    logging.info(f"Created imaging .SXM dataset: {perm_id}")
    img = spm(file_path)
    channels = img.default_channels
    color_scale = get_color_scale_range(img, channels[0])[:2]
    width = str(img.get_param("width")[0])
    height = str(img.get_param("height")[0])

    config_sxm_preview = {
        "Channel": channels[0],  # usually one of these: ['z', 'I', 'dIdV', 'dIdV_Y']
        "X-axis": ["0", width],  # file dependent
        "Y-axis": ["0", height],  # file dependent
        "Color-scale": color_scale,  # file dependent
        "Colormap": "gray",  # [gray, YlOrBr, viridis, cividis, inferno, rainbow, Spectral, RdBu, RdGy]
        "Scaling": "linear",  # ['linear', 'logarithmic']
    }

    config_preview = config_sxm_preview.copy()
    preview = create_preview(session, perm_id, config_preview, tags=["SXM"])
    preview.index = 0
    update_image_with_preview(session, perm_id, 0, preview)

    # config_preview = config_sxm_preview.copy()
    # config_preview['Scaling'] = 'logarithmic'
    # config_preview['Colormap'] = 'inferno'

    # filter_config = [
    #     imaging.ImagingDataSetFilter("Gaussian", {"Sigma":"20", "Truncate":"0.3"}),
    #     imaging.ImagingDataSetFilter("Zero background", {}),
    #     imaging.ImagingDataSetFilter("Laplace", {"Size":"3"})
    # ]

    # preview = create_preview(openbis, perm_id, config_preview, filterConfig=filter_config, tags=['SXM'])
    # preview.index = 1
    # update_image_with_preview(openbis, perm_id, 0, preview)


def demo_dat_flow(session, folder_path, experiment, sample):
    dataset_dat = create_dat_dataset(
        session=session,
        sample=sample,
        experiment=experiment,
        folder_path=folder_path,
        dataset_type="IMAGING_DATA",
    )

    perm_id = dataset_dat.permId
    logging.info(f"Created imaging .DAT dataset: {perm_id}")
    data = spm.importall(folder_path, "spec")

    # Sort dat files by datetime
    data.sort(key=lambda da: da.record_datetime)

    # Select default channels for the selected measurement type
    default_channels = data[0].default_channels
    if default_channels:
        channel_x = default_channels[0]
        channel_y = default_channels[1]
    else:
        data_channels = list(data[0].signals.keys())
        channel_x = data_channels[0]
        channel_y = data_channels[1]

    (minimum_x, maximum_x, step_x) = _min_max_step(channel_x, data)
    (minimum_y, maximum_y, step_y) = _min_max_step(channel_y, data)

    config_dat_preview = {
        "Channel X": channel_x,
        "Channel Y": channel_y,
        "X-axis": [str(minimum_x), str(maximum_x)],
        "Y-axis": [str(minimum_y), str(maximum_y)],
        "Grouping": sorted([os.path.basename(str(f)) for f in data]),
        "Colormap": "rainbow",
        "Scaling": "lin-lin",  # ['lin-lin', 'lin-log', 'log-lin', 'log-log']
        "Print legend": "True",  # disable legend in image
    }

    config_preview = config_dat_preview.copy()
    preview = create_preview(session, perm_id, config_preview, tags=["DAT"])
    preview.index = 0
    update_image_with_preview(session, perm_id, 0, preview)


def create_sxm_dataset(
    session, experiment, file_path, sample=None, dataset_type="IMAGING_DATA"
):
    img = spm(file_path)
    channels = list(img.signals.keys())
    default_channel = img.default_channels[0]

    # Put default channel as first
    channels = [default_channel] + [x for x in channels if x != default_channel]

    # Create openBIS image control object
    imaging_control = ImagingControl(session)

    color_scale_visibility = [
        imaging.ImagingDataSetControlVisibility(
            "Channel",
            [channel],
            get_color_scale_range(img, channel),
            img.get_channel(channel)[1],
        )
        for channel in channels
    ]

    exports = [
        imaging.ImagingDataSetControl(
            "include", "Dropdown", values=["image", "raw data"], multiselect=True
        ),
        imaging.ImagingDataSetControl(
            "image-format",
            "Dropdown",
            values=["png", "svg"],
            semanticAnnotation=imaging.ImagingSemanticAnnotation(
                "schema.org",
                "https://schema.org/version/28.1",
                "https://schema.org/encoding",
            ),
        ),
        imaging.ImagingDataSetControl(
            "archive-format",
            "Dropdown",
            values=["zip", "tar"],
            semanticAnnotation=imaging.ImagingSemanticAnnotation(
                "schema.org",
                "https://schema.org/version/28.1",
                "https://schema.org/fileFormat",
            ),
        ),
        imaging.ImagingDataSetControl(
            "resolution",
            "Dropdown",
            values=["original", "150dpi", "300dpi"],
            semanticAnnotation=None,
        ),
    ]

    inputs = [
        imaging.ImagingDataSetControl(
            "Channel", "Dropdown", values=channels, section="Data"
        ),
        imaging.ImagingDataSetControl(
            "X-axis",
            "Range",
            section="Data",
            values_range=["0", str(img.get_param("width")[0]), "0.01"],
        ),
        imaging.ImagingDataSetControl(
            "Y-axis",
            "Range",
            section="Data",
            values_range=["0", str(img.get_param("height")[0]), "0.01"],
        ),
        imaging.ImagingDataSetControl(
            "Color-scale", "Range", section="Data", visibility=color_scale_visibility
        ),
        imaging.ImagingDataSetControl(
            "Scaling", "Dropdown", section="Data", values=["linear", "logarithmic"]
        ),
        imaging.ImagingDataSetControl(
            "Colormap",
            "Colormap",
            values=[
                "gray",
                "YlOrBr",
                "viridis",
                "cividis",
                "inferno",
                "rainbow",
                "Spectral",
                "RdBu",
                "RdGy",
            ],
            semanticAnnotation=imaging.ImagingSemanticAnnotation(
                "schema.org",
                "https://schema.org/version/28.1",
                "https://schema.org/color",
            ),
        ),
    ]

    filters = {
        "Gaussian": [
            imaging.ImagingDataSetControl(
                "Sigma", "Slider", section="Gaussian", values_range=["1", "100", "1"]
            ),
            imaging.ImagingDataSetControl(
                "Truncate", "Slider", section="Gaussian", values_range=["0", "1", "0.1"]
            ),
        ],
        "Laplace": [
            imaging.ImagingDataSetControl(
                "Size", "Slider", section="Laplace", values_range=["3", "30", "1"]
            )
        ],
        "Zero background": [],
        "Plane Subtraction": [],
        "Line Subtraction": [],
    }

    filterSemanticAnnotation = {
        "Gaussian": imaging.ImagingSemanticAnnotation(
            "schema.org",
            "https://schema.org/version/28.1",
            "https://schema.org/headline",
        )
    }

    imaging_config = imaging.ImagingDataSetConfig(
        adaptor=SXM_ADAPTOR,
        version=1.0,
        resolutions=["original", "200x200", "2000x2000"],
        playable=True,
        speeds=[1000, 2000, 5000],
        exports=exports,
        inputs=inputs,
        metadata={},
        filters=filters,
        filterSemanticAnnotation=filterSemanticAnnotation,
    )

    images = [
        imaging.ImagingDataSetImage(
            imaging_config,
            previews=[imaging.ImagingDataSetPreview(preview_format="png")],
            metadata=img.print_params_dict(False),
        )
    ]
    imaging_property_config = imaging.ImagingDataSetPropertyConfig(images)
    if VERBOSE:
        logging.info(imaging_property_config.to_json())

    return imaging_control.create_imaging_dataset(
        dataset_type=dataset_type,
        config=imaging_property_config,
        experiment=experiment,
        sample=sample,
        files=[file_path],
    )


def create_dat_dataset(
    session, experiment, sample, folder_path, dataset_type="IMAGING_DATA"
):
    data = spm.importall(folder_path, "spec")

    if [] == data:
        raise ValueError(f"No nanonis .DAT files found in {folder_path}")

    imaging_control = ImagingControl(session)

    for d in data:
        date_time = d.get_param("Saved Date")
        d.date_time = (
            datetime.strptime(date_time, "%d.%m.%Y %H:%M:%S")
            if date_time is not None
            else datetime.now()
        )

    data.sort(key=lambda da: da.date_time)
    default_channels = d.default_channels
    if default_channels:
        channel_x, channel_y = default_channels
    else:
        data_channels = list(d.signals.keys())
        channel_x = data_channels[0]
        channel_y = data_channels[1]

    color_scale_visibility_x = []
    color_scale_visibility_y = []
    for dat_file in data:
        # Channel Y
        channel_y_unit = dat_file.signals[channel_y]["ChannelUnit"]

        # Channel X
        channel_x_unit = dat_file.signals[channel_x]["ChannelUnit"]

        minimum_x, maximum_x = [], []
        minimum_y, maximum_y = [], []
        for spec in data:
            channel_x_data = spec.get_channel(f"{channel_x}")[0]
            minimum_x += [np.nanmin(channel_x_data)]
            maximum_x += [np.nanmax(channel_x_data)]

            channel_y_data = spec.get_channel(f"{channel_y}")[0]
            minimum_y += [np.nanmin(channel_y_data)]
            maximum_y += [np.nanmax(channel_y_data)]

        # Channel X (max, min, and step)
        minimum_x = np.nanmin(minimum_x)
        maximum_x = np.nanmax(maximum_x)

        # Channel Y (max, min, and step)
        minimum_y = np.nanmin(minimum_y)
        maximum_y = np.nanmax(maximum_y)

        # Step channel X
        step_x = abs((maximum_x - minimum_x) / 100)
        if step_x >= 1:
            step_x = 1
        elif step_x > 0:
            step_x = 0.01
        else:
            step_x = np.log10(step_x)
            if np.isnan(step_x) or np.isinf(step_x):
                step_x = 0.01
            else:
                step_x = 10 ** np.floor(step_x)

        color_scale_visibility_x += [
            imaging.ImagingDataSetControlVisibility(
                "Channel X",
                [channel_x],
                [str(minimum_x), str(maximum_x), str(step_x)],
                channel_x_unit,
            )
        ]

        # Step channel Y
        step_y = abs((maximum_y - minimum_y) / 100)
        if step_y >= 1:
            step_y = 1
        elif step_y > 0:
            step_y = 0.01
        else:
            step_y = np.log10(step_y)
            if np.isnan(step_y) or np.isinf(step_y):
                step_y = 0.01
            else:
                step_y = 10 ** np.floor(step_y)

        color_scale_visibility_y += [
            imaging.ImagingDataSetControlVisibility(
                "Channel Y",
                [channel_y],
                [str(minimum_y), str(maximum_y), str(step_y)],
                channel_y_unit,
            )
        ]

    exports = [
        imaging.ImagingDataSetControl(
            "include", "Dropdown", values=["image", "raw data"], multiselect=True
        ),
        imaging.ImagingDataSetControl(
            "image-format",
            "Dropdown",
            values=["png", "svg"],
            semanticAnnotation=imaging.ImagingSemanticAnnotation(
                "schema.org",
                "https://schema.org/version/28.1",
                "https://schema.org/encoding",
            ),
        ),
        imaging.ImagingDataSetControl(
            "archive-format",
            "Dropdown",
            values=["zip", "tar"],
            semanticAnnotation=imaging.ImagingSemanticAnnotation(
                "schema.org",
                "https://schema.org/version/28.1",
                "https://schema.org/fileFormat",
            ),
        ),
        imaging.ImagingDataSetControl(
            "resolution", "Dropdown", values=["original", "150dpi", "300dpi"]
        ),
    ]

    channels = list(data[0].signals.keys())
    channels_x = [channel_x] + [x for x in channels if x != channel_x]
    channels_y = [channel_y] + [x for x in channels if x != channel_y]

    inputs = [
        imaging.ImagingDataSetControl(
            "Channel X", "Dropdown", values=[channel for channel in channels_x]
        ),
        imaging.ImagingDataSetControl(
            "Channel Y", "Dropdown", values=[channel for channel in channels_y]
        ),
        imaging.ImagingDataSetControl(
            "X-axis", "Range", visibility=color_scale_visibility_x
        ),
        imaging.ImagingDataSetControl(
            "Y-axis", "Range", visibility=color_scale_visibility_y
        ),
        imaging.ImagingDataSetControl(
            "Grouping", "Dropdown", values=[d.name for d in data], multiselect=True
        ),
        imaging.ImagingDataSetControl(
            "Colormap",
            "Colormap",
            values=[
                "gray",
                "YlOrBr",
                "viridis",
                "cividis",
                "inferno",
                "rainbow",
                "Spectral",
                "RdBu",
                "RdGy",
            ],
        ),
        imaging.ImagingDataSetControl(
            "Scaling", "Dropdown", values=["lin-lin", "lin-log", "log-lin", "log-log"]
        ),
        # imaging.ImagingDataSetControl('Print legend', "Dropdown", values=['True', 'False']),
    ]

    imaging_config = imaging.ImagingDataSetConfig(
        DAT_ADAPTOR,
        1.0,
        ["original", "200x200", "2000x2000"],
        True,
        [1000, 2000, 5000],
        exports,
        inputs,
        {},
    )

    images = [
        imaging.ImagingDataSetImage(
            imaging_config, metadata=data[0].print_params_dict(False)
        )
    ]
    imaging_property_config = imaging.ImagingDataSetPropertyConfig(images)
    if VERBOSE:
        logging.info(imaging_property_config.to_json())

    return imaging_control.create_imaging_dataset(
        dataset_type=dataset_type,
        config=imaging_property_config,
        sample=sample,
        experiment=experiment,
        files=[d.path for d in data],
    )


def process_measurement_files(
    openbis_url, token, data_folder, measurements_id, logging_filepath
):
    session, _ = utils.connect_openbis(openbis_url, token)
    measurement_files = [f for f in os.listdir(data_folder)]
    logging_file = utils.read_json(logging_filepath)

    readable_measurement_files = []
    measurement_datetimes = []

    # Check measurement files and measurement datetimes
    for f in measurement_files:
        # sxm and dat files
        if f.endswith((".sxm", ".dat")):
            img = spm(f"{data_folder}/{f}")
            img_datetime = img.record_datetime
            readable_measurement_files.append(f)
            measurement_datetimes.append(img_datetime)

    # Sort files by datetime first, then filename
    paired = list(zip(measurement_datetimes, readable_measurement_files))
    paired.sort(key=lambda x: (x[0], x[1]))

    # Extract filenames in sorted order
    sorted_measurement_files = [filename for _, filename in paired]

    # Dat files belonging to the same measurement session, i.e., that are consecutive, should be grouped into just one list of files, except when they do not have the same channels.
    grouped_measurement_files = []
    group = []
    for i, f in enumerate(sorted_measurement_files):
        # SXM files are saved alone
        if f.endswith(".sxm"):
            if len(group) > 0:
                grouped_measurement_files.append(group)
                group = []
            grouped_measurement_files.append([f])

        # DAT files, in case they share the same signals and are consecutively acquired, are saved together
        elif f.endswith(".dat"):
            f_img = spm(f"{data_folder}/{f}")
            files_with_different_channels = False

            for file in group:
                img = spm(f"{data_folder}/{file}")
                if img.signals != f_img.signals:
                    files_with_different_channels = True
                    break

            if files_with_different_channels:
                grouped_measurement_files.append(group)
                group = [f]
            else:
                group.append(f)

    if len(group) > 0:
        grouped_measurement_files.append(group)

    for group in grouped_measurement_files:
        # Save sxm files
        if group[0].endswith(".sxm"):
            logging.info(f"SXM file: {group[0]}")
            file_path = os.path.join(data_folder, group[0])

            if file_path not in logging_file["processed_files"]:
                try:
                    measurements_object = session.get_sample(measurements_id)
                    experiment = measurements_object.experiment
                    demo_sxm_flow(
                        session,
                        file_path,
                        sample=measurements_id,
                        experiment=experiment,
                    )
                    logging_file["processed_files"].append(file_path)
                    utils.write_json(logging_file, logging_filepath)

                except (ValueError, KeyError) as e:
                    logging.info(f"Cannot upload {file_path}. Reason: {e}")
                    # Report it in a logging file
            else:
                logging.info(f"{file_path} already in openBIS.")
        else:
            # Split the dat files by measurement type (e.g.: bias spec dI vs V in one list, bias spec z vs V in another list, etc.)
            dat_files_types = []
            for dat_file in group:
                dat_filename = f"{data_folder}/{dat_file}"
                dat_data = spm(dat_filename)
                dat_files_types.append(dat_data.measurement_type)

            grouped = defaultdict(list)
            for item1, item2 in zip(group, dat_files_types):
                grouped[item2].append(item1)

            dat_files_grouped_by_type = list(grouped.values())

            # Save dat files
            for dat_files_group in dat_files_grouped_by_type:
                dat_files_directory = os.path.join(data_folder, "dat_files")
                shutil.rmtree(dat_files_directory, ignore_errors=True)
                os.mkdir(dat_files_directory)

                delete_original_openBIS_dataset = False
                group_in_openbis = False
                for dat_file in dat_files_group:
                    original_dat_path = os.path.join(data_folder, dat_file)
                    temporary_dat_path = os.path.join(dat_files_directory, dat_file)
                    shutil.copy(original_dat_path, temporary_dat_path)

                    if original_dat_path in logging_file["processed_files"]:
                        group_in_openbis = True
                    else:
                        delete_original_openBIS_dataset = True
                        logging_file["processed_files"].append(original_dat_path)

                if group_in_openbis:
                    if delete_original_openBIS_dataset:
                        try:
                            measurements_object = session.get_sample(measurements_id)
                            experiment = measurements_object.experiment

                            # Delete old dataset in order to update it
                            measurements_datasets = (
                                measurements_object.get_datasets().df.sort_values(
                                    "registrationDate", ascending=False
                                )
                            )
                            dataset_to_remove = measurements_datasets.iloc[0]["permId"]
                            session.get_dataset(dataset_to_remove).delete(
                                "update dataset group"
                            )

                            # Upload dat files
                            demo_dat_flow(
                                session,
                                dat_files_directory,
                                sample=measurements_id,
                                experiment=experiment,
                            )
                            utils.write_json(logging_file, logging_filepath)

                        except ValueError as e:
                            logging.info(
                                f"Cannot upload {dat_files_directory}. Reason: {e}"
                            )
                            # Report it in a logging file
                else:
                    try:
                        measurements_object = session.get_sample(measurements_id)
                        experiment = measurements_object.experiment
                        # Upload dat files
                        demo_dat_flow(
                            session,
                            dat_files_directory,
                            sample=measurements_id,
                            experiment=experiment,
                        )
                        utils.write_json(logging_file, logging_filepath)
                    except ValueError as e:
                        logging.info(
                            f"Cannot upload {dat_files_directory}. Reason: {e}"
                        )
                shutil.rmtree(dat_files_directory)

    session.logout()


if __name__ == "__main__":
    correct_arguments = False

    # Retrieve arguments
    if len(sys.argv) == 6:
        openbis_url = sys.argv[1]
        token = sys.argv[2]
        data_folder = sys.argv[3]
        sample = sys.argv[4]  # PermID
        logging_filepath = sys.argv[5]
        correct_arguments = True
    else:
        print("A required argument is missing.")
        print(
            "Usage: python3 nanonis_importer.py <OPENBIS_URL> <OPENBIS_TOKEN> <PATH_TO_DATA_FOLDER> <MEASUREMENTS_PERMID> <LOGGING_FILEPATH>"
        )

    if correct_arguments:
        process_measurement_files(
            openbis_url, token, data_folder, sample, logging_filepath
        )
