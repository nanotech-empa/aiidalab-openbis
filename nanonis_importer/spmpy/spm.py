import os
import re
import warnings
import matplotlib.pyplot as plt
import numpy as np
import spiepy
import yaml
import datetime
from matplotlib.colors import LogNorm
from . import nanonispy as nap


class Spm:
    current_abspath = os.path.abspath(__file__)
    current_directory = os.path.dirname(current_abspath)
    DEFAULT_CONFIG = os.path.join(current_directory, "machine_config.yaml")

    def __init__(self, path: str, config_file=DEFAULT_CONFIG):
        # Configuration parameters
        config = self.load_machine_configuration_from_yaml_file(config_file)

        # Get name, path, and file extension
        abspath = os.path.abspath(path)
        split_abspath = abspath.split("\\")
        self.path = "/".join(split_abspath)
        self.name = self.path.split("/")[-1]
        file_extension = os.path.splitext(self.name)[-1]

        if file_extension == ".sxm":
            self.napImport = nap.read.Scan(path)
            self.napImport.header["z-controller>tiplift (m)"] = (
                self.napImport.header.get("z-controller>tiplift (m)", 0)
            )
            self.napImport.header["z-controller>setpoint"] = float(
                self.napImport.header["z-controller"]["Setpoint"][0].split(" ")[0]
            )
            self.type = "scan"
            self.header = self.napImport.header
            self.record_datetime = datetime.datetime.strptime(
                f"{self.header['rec_date']} {self.header['rec_time']}",
                "%d.%m.%Y %H:%M:%S",
            )
        elif file_extension == ".dat":
            self.napImport = nap.read.Spec(path)
            self.type = "spec"
            self.header = self.napImport.header
            if "Saved Date" in self.header:
                self.record_datetime = datetime.datetime.strptime(
                    self.header["Saved Date"], "%d.%m.%Y %H:%M:%S"
                )
            elif "Date" in self.header:
                self.record_datetime = datetime.datetime.strptime(
                    self.header["Date"], "%d.%m.%Y %H:%M:%S"
                )
        elif file_extension == ".3ds":
            self.napImport = nap.read.Grid(path)
            self.type = "grid"
        else:
            print("Datatype not supported.")
            return

        self.signals = {}
        for key in self.napImport.signals.keys():
            channel_name = key
            channel_nickname = key
            channel_scaling = 1.0
            channel_unit = "N/A"

            if key in config["Channels"]:
                channel_nickname = config["Channels"][key]["nickname"]
                channel_scaling = config["Channels"][key]["scaling"]
                channel_unit = config["Channels"][key]["unit"]

            channel_info = {
                "ChannelName": channel_name,
                "ChannelScaling": channel_scaling,
                "ChannelUnit": channel_unit,
            }

            self.signals[channel_nickname] = channel_info

        self.parameters = {}
        for key in config["Parameters"].keys():
            parameter_nickname = config["Parameters"][key]["nickname"]
            parameter_scaling = config["Parameters"][key]["scaling"]
            parameter_unit = config["Parameters"][key]["unit"]
            parameter_info = {
                "ParamName": parameter_nickname,
                "ParamScaling": parameter_scaling,
                "ParamUnit": parameter_unit,
            }
            self.parameters[key] = parameter_info
            # self.parameters[parameter_nickname] = parameter_info

        self.default_channels, self.measurement_type = self.__get_default_channels()

    def load_machine_configuration_from_yaml_file(self, filepath):
        """
        Load the machine configuration from a yaml file.

        Inputs:
        -------
        filepath: str
            Path to the yaml file

        Outputs:
        --------
        config: dict
            Dictionary containing the machine configuration
        """

        # Define specific loader for float values
        mode = "r"
        loader = yaml.SafeLoader
        loader.add_implicit_resolver(
            "tag:yaml.org,2002:float",
            re.compile(
                """^(?:
            [-+]?(?:[0-9][0-9_]*)\\.[0-9_]*(?:[eE][-+]?[0-9]+)?
            |[-+]?(?:[0-9][0-9_]*)(?:[eE][-+]?[0-9]+)
            |\\.[0-9_]+(?:[eE][-+][0-9]+)?
            |[-+]?[0-9][0-9_]*(?::[0-5]?[0-9])+\\.[0-9_]*
            |[-+]?\\.(?:inf|Inf|INF)
            |\\.(?:nan|NaN|NAN))$""",
                re.X,
            ),
            list("-+0123456789."),
        )

        # Load the yaml file
        with open(filepath, mode=mode) as fhandle:
            config = yaml.load(fhandle, Loader=loader)

        # Check if the machine configuration is set to THzSTM
        if config["MachineConfig"] != "THzSTM":
            warnings.warn("MachineConfig not set to THzSTM")

        return config

    def __repr__(self):
        return self.path

    def __get_default_channels(self):
        measurement_type = ""
        default_channels = []

        if self.type == "scan":
            """
            Lock-in>Lock-in status: ON > dIdV vs V
            Lock-in>Lock-in status: OFF:
                Z-Ctrl hold: TRUE > z vs V
                Z-Ctrl hold: FALSE:
                    Oscillation Control>output off: TRUE > df vs V
                    Oscillation Control>output off: FALSE > I vs V
            """
            # Get Lock-in status
            lock_in_status = None
            if "lock-in>lock-in status" in self.header:
                if self.header["lock-in>lock-in status"] == "ON":
                    lock_in_status = True
                else:
                    lock_in_status = False

            # Get Z-controller status
            z_controller_status = None
            if "z-controller" in self.header:
                if "on" in self.header["z-controller"]:
                    if self.header["z-controller"]["on"][0] == "1":
                        z_controller_status = True
                    else:
                        z_controller_status = False

            # Get oscillation control output off status
            oscillation_control_output_off = None
            if "oscillation control>output off" in self.header:
                if self.header["oscillation control>output off"] == "TRUE":
                    oscillation_control_output_off = True
                else:
                    oscillation_control_output_off = False

            try:
                if lock_in_status:
                    default_channel = "dIdV"
                    measurement_type = "dI/dV image"
                elif not lock_in_status:
                    if z_controller_status:
                        default_channel = "z"
                        measurement_type = "STM image"
                    else:
                        if oscillation_control_output_off:
                            default_channel = "df"
                            measurement_type = "AFM image"
                        else:
                            default_channel = "I"
                            measurement_type = "Current image"
                else:
                    default_channel = (
                        "z" if "z" in self.signals else next(iter(self.signals))
                    )  # Select first channel available
                    measurement_type = "Image"
            except Exception:
                default_channel = next(iter(self.signals))
                measurement_type = "Image"

            default_channels = [default_channel]

        elif self.type == "spec":
            """
            Bias spectroscopy:
                Lock-in>Lock-in status: ON > dIdV vs V
                Lock-in>Lock-in status: OFF
                    Z-Ctrl hold: TRUE > z vs V
                    Z-Ctrl hold: FALSE
                        Oscillation Control>output off: TRUE > df vs V
                        Oscillation Control>output off: FALSE > I vs V

            Z spectroscopy:
                Lock-in>Lock-in status: ON > dIdV vs z
                Lock-in>Lock-in status: OFF
                    Oscillation Control>output off: TRUE > df vs z
                    Oscillation Control>output off: FALSE > I vs z
            """

            default_channels = []
            measurement_type = ""
            # Get Lock-in status
            lock_in_status = None
            if "Lock-in>Lock-in status" in self.header:
                if self.header["Lock-in>Lock-in status"] == "ON":
                    lock_in_status = True
                else:
                    lock_in_status = False

            # Get Z-control hold status
            z_control_hold = None
            if "Z-Ctrl hold" in self.header:
                if self.header["Z-Ctrl hold"] == "TRUE":
                    z_control_hold = True
                else:
                    z_control_hold = False

            # Get oscillation control output off status
            oscillation_control_output_off = None
            if "oscillation control>output off" in self.header:
                if self.header["oscillation control>output off"] == "TRUE":
                    oscillation_control_output_off = True
                else:
                    oscillation_control_output_off = False

            measurement_type = self.header.get("Experiment")
            if self.header.get("Experiment") == "bias spectroscopy":
                if lock_in_status:
                    if "V" in self.signals and "dIdV" in self.signals:
                        measurement_type += " dIdV vs V"
                        default_channels = ["V", "dIdV"]
                elif not lock_in_status:
                    if not z_control_hold:
                        if "zspec" in self.signals and "V" in self.signals:
                            measurement_type += " z vs V"
                            default_channels = ["V", "zspec"]
                    else:
                        if oscillation_control_output_off:
                            if "V" in self.signals and "df" in self.signals:
                                measurement_type += " df vs V"
                                default_channels = ["V", "df"]
                        else:
                            if "V" in self.signals and "I" in self.signals:
                                measurement_type += " I vs V"
                                default_channels = ["V", "I"]
            elif self.header.get("Experiment") == "Z spectroscopy":
                if lock_in_status:
                    if "zspec" in self.signals and "dIdV" in self.signals:
                        measurement_type += " dIdV vs z"
                        default_channels = ["zspec", "dIdV"]
                elif not lock_in_status:
                    if oscillation_control_output_off:
                        if "zspec" in self.signals and "df" in self.signals:
                            measurement_type += " df vs z"
                            default_channels = ["zspec", "df"]
                    else:
                        if "zspec" in self.signals and "I" in self.signals:
                            measurement_type += " I vs z"
                            default_channels = ["zspec", "I"]

        return default_channels, measurement_type

    # get channel
    def get_channel(
        self,
        channel: str,
        direction: str = "forward",
        flatten: bool = False,
        offset: bool = False,
        zero: bool = False,
    ):
        """
        Returns the measurement values and the channel unit.

        Parameters
        ----------
        channel : str
            Name of the channel stored in the reference config file or in the NANONIS file.
        direction : str, optional
            Measurement direction. It can only be forward or backward. The default is 'forward'.
        flatten : bool, optional
            Substract background plane from image data. The default is False.
        offset : bool, optional
            Substract constant offset = mean value. The default is False.
        zero : bool, optional
            Substract constant offset = minimum value. The default is False.

        Returns
        -------
        tuple
            Measurement values and channel unit

        """

        if self.type == "scan":
            channel_name = self.signals[channel]["ChannelName"]
            channel_scaling = self.signals[channel]["ChannelScaling"]
            im = self.napImport.signals[channel_name][direction]
            im = im * channel_scaling

            if flatten:
                if ~np.isnan(np.sum(im)):
                    im, _ = spiepy.flatten_xy(im)
                else:
                    m, n = np.shape(im)
                    i = np.argwhere(np.isnan(im))[0, 0]
                    im_cut = im[: i - 1, :]
                    im, _ = spiepy.flatten_xy(im_cut)
                    empty = np.full((m - i, n), np.nan)
                    im = np.vstack((im, empty))

                    warnings.warn("NaN values in image")
                    # im-np.nanmean(im)

            if offset:
                im = im - np.mean(im)
            if zero:
                im = im + abs(np.min(im))

            unit = self.signals[channel]["ChannelUnit"]

            return (im, unit)

        elif self.type == "spec":
            if direction == "backward":
                channel = channel + "_bw"

            channel_name = self.signals[channel]["ChannelName"]
            channel_scaling = self.signals[channel]["ChannelScaling"]
            data = self.napImport.signals[channel_name]
            data = data * channel_scaling
            unit = self.signals[channel]["ChannelUnit"]

            return (data, unit)

        elif self.type == "grid":
            if direction == "backward":
                channel = channel + "_bw"
                # print(channel)

            chNum = [d["ChannelNickname"] for d in self.SignalsList].index(channel)
            data = self.napImport.signals[self.SignalsList[chNum]["ChannelName"]]
            data = data * self.SignalsList[chNum]["ChannelScaling"]
            unit = self.SignalsList[chNum]["ChannelUnit"]

            return (data, unit)

        return

    # get parameter
    def get_param(self, param: str):
        """
        Returns the parameter value and the parameter unit.

        Parameters
        ----------
        param : str
            Name of the parameter stored in the reference config file or in the NANONIS file.

        Returns
        -------
        TYPE
            DESCRIPTION.

        """

        if param in self.parameters:
            parameter_scaling = self.parameters[param]["ParamScaling"]

            if parameter_scaling is None:
                return self.napImport.header[param]
            else:
                value = np.float64(self.napImport.header[param]) * parameter_scaling
                unit = self.parameters[param]["ParamUnit"]
                return (value, unit)

        elif param == "width" or param == "height":
            unit = self.parameters["scan_range"]["ParamUnit"]
            parameter_scaling = self.parameters["scan_range"]["ParamScaling"]
            if param == "width":
                value = self.get_param("scan_range")[0][0]
            elif param == "height":
                value = self.get_param("scan_range")[0][1]

            return (value, unit)

        else:
            return self.napImport.header.get(param, None)

    # print essential parameters for plotting
    def print_params(self, show: bool = True):
        """
        Print essential parameters for plotting

        Parameters
        ----------
        show : bool, optional
            Whether label if printed. The default is True.

        Returns
        -------
        label : list
            Set of important parameters.

        """

        label = []

        if self.type == "scan":
            parameters = {
                "fb_enable": "z-controller>controller status",
                "bias": "V",
                "set_point": "setpoint",
                "z_offset": "z_offset",
                "comment": "comments",
                "height": "height",
                "width": "width",
                "angle": "angle",
                "controller": "z-controller>controller name",
                "date": "rec_date",
                "time": "rec_time",
                "acq_time": "acq_time",
            }
            for key, value in parameters.items():
                try:
                    parameters[key] = self.get_param(value)
                except KeyError as err:
                    print(f"Missing Header Key, {err}")
                    parameters[key] = "N/A"
                except Exception:
                    parameters[key] = "N/A"

            fb_enable = parameters["fb_enable"]
            bias = parameters["bias"]
            set_point = parameters["set_point"]
            z_offset = parameters["z_offset"]
            date = parameters["date"]
            time = parameters["time"]
            comment = parameters["comment"]
            parameters["controller"]
            parameters["height"]
            parameters["width"]
            parameters["angle"]
            if fb_enable == "OFF":
                label.append("constant height")
                label.append(f"z-offset: {z_offset[0]:.3f}{z_offset[1]}")

            if np.abs(bias[0]) < 0.1:
                bias = list(bias)
                bias[0] = bias[0] * 1000
                bias[1] = "mV"
                bias = tuple(bias)

            label.append(f"Bias = {bias[0]:.2f}{bias[1]}")
            label.append(f"I = {set_point[0]:.0f}{set_point[1]}")
            label.append(f"Measurement type = {self.measurement_type}")
            label.append(f"comment: {comment}")
            label.append(f"Date: {date} - {time}")

        elif self.type == "spec":
            parameters = {
                "fb_enable": "Z-Ctrl hold",
                "bias": "V_spec",
                "set_point": "setpoint_spec",
                "z_offset": "Bias Spectroscopy>Z offset (m)",
                "comment": "comments",
                "lockin_amplitude": "lockin_amplitude",
                "lockin_phase": "lockin_phase",
                "lockin_frequency": "lockin_frequency",
                "lockin_status": "Lock-in>Lock-in status",
                "date": "Saved Date",
            }
            for key, value in parameters.items():
                try:
                    parameters[key] = self.get_param(value)
                except KeyError as err:
                    print(f"Missing Header Key, {err}")
                    parameters[key] = "N/A"
                except Exception:
                    parameters[key] = "N/A"

            fb_enable = parameters["fb_enable"]
            bias = parameters["bias"]
            set_point = parameters["set_point"]
            z_offset = parameters["z_offset"]
            date = parameters["date"]
            parameters["lockin_status"]
            lockin_amplitude = parameters["lockin_amplitude"]
            lockin_phase = parameters["lockin_phase"]
            lockin_frequency = parameters["lockin_frequency"]
            comment = parameters["comment"]

            # if lockin_status == 'ON':
            label.append(
                f"lockin: A = {lockin_amplitude[0]:.0f}{lockin_amplitude[1]} (θ = {lockin_phase[0]:.0f}{lockin_phase[1]}, f = {lockin_frequency[0]:.0f}{lockin_frequency[1]})"
            )

            if fb_enable == "FALSE":
                label.append("feedback on")

            elif fb_enable == "TRUE":
                label.append("feedback off")

            label.append(
                f"setpoint: I = {set_point[0]:.0f}{set_point[1]}, V = {bias[0]:.1f}{bias[1]}"
            )
            label.append(f"comment: {comment}")
            label.append(f"Date: {date}")

        # label.append(f"path: {self.path}")
        label = "\n".join(label)

        if show:
            print(label)

        return label

    def print_params_dict(self, show=True):
        label = dict()

        if self.type == "scan":
            parameters = {
                "z-controller_status": "z-controller>controller status",
                "z-controller_name": "z-controller>controller name",
                "bias": "bias",
                "z-controller_setpoint": "z-controller>setpoint",
                "comment": "comments",
                "height": "height",
                "width": "width",
                "angle": "scan_angle",
                "date": "rec_date",
                "time": "rec_time",
                "lock_in_amplitude": "lock-in>amplitude",
                "lock_in_frequency": "lock-in>frequency (hz)",
                "lock_in_phase": "lock-in>reference phase d1 (deg)",
                "oscillation_control_frequency": "oscillation control>center frequency (hz)",
                "oscillation_control_amplitude_ctrl": "oscillation control>amplitude controller on",
                "oscillation_control_amplitude_setpoint": "oscillation control>amplitude setpoint (m)",
            }

            for key, value in parameters.items():
                try:
                    parameters[key] = self.get_param(value)
                except KeyError as err:
                    print(f"Missing Header Key, {err}")
                    parameters[key] = "N/A"
                except Exception:
                    parameters[key] = "N/A"

            if parameters["z-controller_status"] is None:
                parameters["z-controller_status"] = self.header["z-controller"]["on"][0]

            if parameters["z-controller_setpoint"] is None:
                setpoint_values = self.header["z-controller"]["Setpoint"][0].split()
                parameters["z-controller_setpoint"] = (
                    np.float64(setpoint_values[0]),
                    setpoint_values[1],
                )

            if self.measurement_type == "dI/dV image":
                label["z-controller (status)"] = parameters["z-controller_status"]
                label["z-controller (setpoint)"] = (
                    "%.2f %s" % parameters["z-controller_setpoint"]
                )
                label["lock-in (amplitude)"] = (
                    "%.2f %s" % parameters["lock_in_amplitude"]
                )
                label["lock-in (frequency)"] = (
                    "%.2f %s" % parameters["lock_in_frequency"]
                )
                label["lock-in (phase)"] = "%.2f %s" % parameters["lock_in_phase"]

            elif self.measurement_type == "STM image":
                label["z-controller (status)"] = parameters["z-controller_status"]
                label["z-controller (setpoint)"] = (
                    "%.2f %s" % parameters["z-controller_setpoint"]
                )

            elif self.measurement_type == "AFM image":
                label["oscillation control (center frequency)"] = (
                    "%.2f %s" % parameters["oscillation_control_frequency"]
                )
                label["oscillation control (amplitude controller)"] = parameters[
                    "oscillation_control_amplitude_ctrl"
                ]
                label["oscillation control (amplitude setpoint)"] = (
                    "%.2f %s" % parameters["oscillation_control_amplitude_setpoint"]
                )

            elif self.measurement_type == "Current image":
                label["z-controller (status)"] = parameters["z-controller_status"]
            else:
                label["z-controller (status)"] = parameters["z-controller_status"]
                label["z-controller (setpoint)"] = (
                    "%.2f %s" % parameters["z-controller_setpoint"]
                )

            label["bias"] = "%.2f %s" % parameters["bias"]
            label["size"] = "%.2f %s x %.2f %s (%.2f%s)" % (
                parameters["width"] + parameters["height"] + parameters["angle"]
            )
            label["measurement type"] = self.measurement_type
            label["start date"] = f"{parameters['date']} {parameters['time']}"
            label["title"] = self.name
            label["comment"] = parameters["comment"]

        elif self.type == "spec":
            parameters = {
                "bias": "Bias>Bias (V)",
                "date": "Saved Date",
                "z-controller_hold": "Z-Ctrl hold",
                "z-controller_setpoint": "Z-Controller>Setpoint",
                "lock_in_amplitude": "Lock-in>Amplitude",
                "lock_in_frequency": "Lock-in>Frequency (Hz)",
                "lock_in_phase": "Lock-in>Reference Phase D1 (deg)",
                "oscillation_control_frequency": "Oscillation Control>Center Frequency (Hz)",
                "oscillation_control_amplitude_ctrl": "Oscillation Control>Amplitude controller on",
                "oscillation_control_amplitude_setpoint": "Oscillation Control>Amplitude Setpoint (m)",
            }

            for key, value in parameters.items():
                try:
                    parameters[key] = self.get_param(value)
                except KeyError as err:
                    print(f"Missing Header Key, {err}")
                    parameters[key] = "N/A"
                except Exception:
                    parameters[key] = "N/A"

            if "bias spectroscopy" in self.measurement_type:
                if self.measurement_type == "bias spectroscopy dIdV vs V":
                    label["lock-in (amplitude)"] = (
                        "%.2f %s" % parameters["lock_in_amplitude"]
                    )
                    label["lock-in (frequency)"] = (
                        "%.2f %s" % parameters["lock_in_frequency"]
                    )
                    label["lock-in (phase)"] = "%.2f %s" % parameters["lock_in_phase"]
                    label["z-controller (setpoint)"] = (
                        "%.2f %s" % parameters["z-controller_setpoint"]
                    )
                    label["z-controller (hold)"] = parameters["z-controller_hold"]

                elif self.measurement_type == "bias spectroscopy z vs V":
                    label["z-controller (setpoint)"] = (
                        "%.2f %s" % parameters["z-controller_setpoint"]
                    )
                    label["z-controller (hold)"] = parameters["z-controller_hold"]

                elif self.measurement_type == "bias spectroscopy df vs V":
                    label["oscillation control (center frequency)"] = (
                        "%.2f %s" % parameters["oscillation_control_frequency"]
                    )
                    label["oscillation control (amplitude controller)"] = parameters[
                        "oscillation_control_amplitude_ctrl"
                    ]
                    label["oscillation control (amplitude setpoint)"] = (
                        "%.2f %s" % parameters["oscillation_control_amplitude_setpoint"]
                    )

                elif self.measurement_type == "bias spectroscopy I vs V":
                    label["z-controller (hold)"] = parameters["z-controller_hold"]
                    if len(parameters["z-controller_setpoint"]) == 2:
                        label["z-controller (setpoint)"] = (
                            "%.2f %s" % parameters["z-controller_setpoint"]
                        )
                    else:
                        label["z-controller (setpoint)"] = parameters[
                            "z-controller_setpoint"
                        ]

                else:
                    label["z-controller (hold)"] = parameters["z-controller_hold"]
                    if len(parameters["z-controller_setpoint"]) == 2:
                        label["z-controller (setpoint)"] = (
                            "%.2f %s" % parameters["z-controller_setpoint"]
                        )
                    else:
                        label["z-controller (setpoint)"] = parameters[
                            "z-controller_setpoint"
                        ]

            elif "Z spectroscopy" in self.measurement_type:
                label["bias"] = "%.2f %s" % parameters["bias"]

                # There are files where this parameter is not available
                if len(parameters["z-controller_setpoint"]) == 2:
                    label["z-controller (setpoint)"] = (
                        "%.2f %s" % parameters["z-controller_setpoint"]
                    )
                else:
                    label["z-controller (setpoint)"] = parameters[
                        "z-controller_setpoint"
                    ]

                if self.measurement_type == "Z spectroscopy dIdV vs z":
                    label["lock-in (amplitude)"] = (
                        "%.2f %s" % parameters["lock_in_amplitude"]
                    )
                    label["lock-in (frequency)"] = (
                        "%.2f %s" % parameters["lock_in_frequency"]
                    )
                    label["lock-in (phase)"] = "%.2f %s" % parameters["lock_in_phase"]

                elif self.measurement_type == "Z spectroscopy df vs z":
                    label["z-controller (setpoint)"] = (
                        "%.2f %s" % parameters["z-controller_setpoint"]
                    )
                    label["oscillation control (center frequency)"] = (
                        "%.2f %s" % parameters["oscillation_control_frequency"]
                    )
                    label["oscillation control (amplitude controller)"] = parameters[
                        "oscillation_control_amplitude_ctrl"
                    ]
                    label["oscillation control (amplitude setpoint)"] = (
                        "%.2f %s" % parameters["oscillation_control_amplitude_setpoint"]
                    )

        return label

    # plot
    def plot(self, **params):
        """
        Plots a channel of the Spm objects

        Parameters
        ----------
        **params : TYPE
            Optional parameters for .sxm files:
                channel: Name of the channel that is plotted
                direction: Measurement direction (forward or backward)
                flatten: Boolean whether the plane subtraction
                offset: Boolean whether the constant offset (mean value) should be subtracted
                cmap: Name of color map
                clim: Lower bound and upper bound of the color limits
                log: Boolean whether the color scale is logarithmic
                show_params: Whether in the title essential parameters are shown
                show: Whether the plot is shown
                save: Whether plot is saved
                save_name: Name of the saved plot
                close_fig: Whether figure is closed at the end
                save_format: Save format
                zero: Boolean whether the constant offset (minimum value) should be subtracted

            Optional parameters for .dat files:
                channelx: Name of the X channel
                channely: Name of the Y channel
                direction: Measurement direction (forward or backward)
                log: Boolean whether the color scale is logarithmic
                loglog: Log-log plot
                show_params: Whether in the title essential parameters are shown
                show: Whether the plot is shown
                save: Whether plot is saved
                save_name: Name of the saved plot
                close_fig: Whether figure is closed at the end
                save_format: Save format

        Returns
        -------
        fig : matplotlib.pyplot.Figure
            Figure of a channel of the Spm object

        """

        # cmaps = sorted(m for m in plt.cm.datad)
        # ['Accent', 'Accent_r', 'Blues', 'Blues_r', 'BrBG', 'BrBG_r', 'BuGn', 'BuGn_r', 'BuPu', 'BuPu_r', 'CMRmap', 'CMRmap_r', 'Dark2', 'Dark2_r', 'GnBu', 'GnBu_r', 'Greens', 'Greens_r', 'Greys', 'Greys_r', 'OrRd', 'OrRd_r', 'Oranges', 'Oranges_r', 'PRGn', 'PRGn_r', 'Paired', 'Paired_r', 'Pastel1', 'Pastel1_r', 'Pastel2', 'Pastel2_r', 'PiYG', 'PiYG_r', 'PuBu', 'PuBuGn', 'PuBuGn_r', 'PuBu_r', 'PuOr', 'PuOr_r', 'PuRd', 'PuRd_r', 'Purples', 'Purples_r', 'RdBu', 'RdBu_r', 'RdGy', 'RdGy_r', 'RdPu', 'RdPu_r', 'RdYlBu', 'RdYlBu_r', 'RdYlGn', 'RdYlGn_r', 'Reds', 'Reds_r', 'Set1', 'Set1_r', 'Set2', 'Set2_r', 'Set3', 'Set3_r', 'Spectral', 'Spectral_r', 'Wistia', 'Wistia_r', 'YlGn', 'YlGnBu', 'YlGnBu_r', 'YlGn_r', 'YlOrBr', 'YlOrBr_r', 'YlOrRd', 'YlOrRd_r', 'afmhot', 'afmhot_r', 'autumn', 'autumn_r', 'binary', 'binary_r', 'bone', 'bone_r', 'brg', 'brg_r', 'bwr', 'bwr_r', 'cool', 'cool_r', 'coolwarm', 'coolwarm_r', 'copper', 'copper_r', 'cubehelix', 'cubehelix_r', 'flag', 'flag_r', 'gist_earth', 'gist_earth_r', 'gist_gray', 'gist_gray_r', 'gist_heat', 'gist_heat_r', 'gist_ncar', 'gist_ncar_r', 'gist_rainbow', 'gist_rainbow_r', 'gist_stern', 'gist_stern_r', 'gist_yarg', 'gist_yarg_r', 'gnuplot', 'gnuplot2', 'gnuplot2_r', 'gnuplot_r', 'gray', 'gray_r', 'hot', 'hot_r', 'hsv', 'hsv_r', 'jet', 'jet_r', 'nipy_spectral', 'nipy_spectral_r', 'ocean', 'ocean_r', 'pink', 'pink_r', 'prism', 'prism_r', 'rainbow', 'rainbow_r', 'seismic', 'seismic_r', 'spectral', 'spectral_r', 'spring', 'spring_r', 'summer', 'summer_r', 'terrain', 'terrain_r', 'winter', 'winter_r']

        # ml.interactive(0)

        if self.type == "scan":
            if "channel" in params:
                channel = params["channel"]
            else:
                channel = self.channels[0]

            if "direction" in params:
                direction = params["direction"]
            else:
                direction = "forward"

            if "flatten" in params:
                flatten = params["flatten"]
            else:
                flatten = False

            if "offset" in params:
                offset = params["offset"]
            else:
                offset = False

            if "cmap" in params:
                cmap = params["cmap"]
            else:
                cmap = "gray"

            if "clim" in params:
                clim = params["clim"]
            else:
                clim = False

            if "log" in params:
                log = params["log"]
            else:
                log = False

            if "show_params" in params:
                show_params = params["show_params"]
            else:
                show_params = False

            if "show" in params:
                show = params["show"]
            else:
                show = True

            if "save" in params:
                save = params["save"]
            else:
                save = False

            if "save_name" in params:
                save_name = params["save_name"]
            else:
                save_name = False

            if "close_fig" in params:
                close_fig = params["close_fig"]
            else:
                close_fig = True

            if "save_format" in params:
                save_format = params["save_format"]
            else:
                save_format = "png"

            if "zero" in params:
                zero = params["zero"]
            else:
                zero = False

            (chData, chUnit) = self.get_channel(
                channel, direction=direction, flatten=flatten, offset=offset, zero=zero
            )

            if "vmin" in params:
                vmin = params["vmin"]
            else:
                vmin = np.min(chData)

            if "vmax" in params:
                vmax = params["vmax"]
            else:
                vmax = np.max(chData)

            if direction == "backward":
                chData = np.fliplr(chData)

            width = self.get_param("scan_range")[0]
            height = self.get_param("scan_range")[1]
            pix_y, pix_x = np.shape(chData)

            fig = plt.figure(figsize=(7, 8))

            ImgOrigin = "lower"
            if self.get_param("scan_dir") == "down":
                ImgOrigin = "upper"

            if log:
                im = plt.imshow(
                    np.abs(chData),
                    aspect="equal",
                    extent=[0, width[0], 0, height[0]],
                    cmap=cmap,
                    norm=LogNorm(),
                    origin=ImgOrigin,
                )
            else:
                im = plt.imshow(
                    chData,
                    aspect="equal",
                    extent=[0, width[0], 0, height[0]],
                    vmin=vmin,
                    vmax=vmax,
                    cmap=cmap,
                    origin=ImgOrigin,
                )

            if clim:
                plt.clim(clim)

            im.axes.set_xticks([0, width[0]])
            im.axes.set_xticklabels([0, np.round(width[0], 2)])
            im.axes.set_yticks([0, height[0]])
            im.axes.set_yticklabels([0, np.round(height[0], 2)])

            if show_params:
                title = self.print_params(show=False)
            else:
                title = self.path

            plt.title(title + "\n", loc="left")
            plt.xlabel(f"x ({width[1]})")
            plt.ylabel(f"y ({height[1]})")

            cbar = plt.colorbar(
                im, fraction=0.046, pad=0.02, format="%.2g", shrink=0.5, aspect=10
            )
            cbar.set_label(f"{channel} ({chUnit}")

            if show:
                plt.show()
            # else:
            #     plt.close(fig)

            if close_fig:
                plt.close(fig)

            if save:
                if save_name:
                    fname = save_name
                else:
                    fname = self.path.split("/")[-1]
                    fname = fname.split(".")[-2]
                fig.savefig(fname + "." + save_format, dpi=500)

            return fig

        elif self.type == "spec":
            if "channelx" in params:
                channelx = params["channelx"]
            else:
                channelx = self.channels[0]

            if "channely" in params:
                channely = params["channely"]
            else:
                channely = self.channels[1]

            if "direction" in params:
                direction = params["direction"]
            else:
                direction = direction = "forward"

            if "log" in params:
                log = params["log"]
            else:
                log = False

            if "loglog" in params:
                loglog = params["loglog"]
            else:
                loglog = False

            if "show_params" in params:
                show_params = params["show_params"]
            else:
                show_params = False

            if "show" in params:
                show = params["show"]
            else:
                show = True

            if "save" in params:
                save = params["save"]
            else:
                save = False

            if "save_name" in params:
                save_name = params["save_name"]
            else:
                save_name = False

            if "close_fig" in params:
                close_fig = params["close_fig"]
            else:
                close_fig = True

            if "save_format" in params:
                save_format = params["save_format"]
            else:
                save_format = "png"

            (x_data, x_unit) = self.get_channel(channelx, direction=direction)
            (y_data, y_unit) = self.get_channel(channely, direction=direction)

            fig = plt.figure(figsize=(6, 4))

            if log:
                plt.semilogy(x_data, np.abs(y_data))

            elif loglog:
                plt.loglog(np.abs(x_data), np.abs(y_data))

            else:
                plt.plot(x_data, y_data)

            if show_params:
                title = self.print_params(show=False)
            else:
                title = self.path

            plt.title(title + "\n", loc="left")

            plt.xlabel(f"{channelx} ({x_unit})")
            plt.ylabel(f"{channely} ({y_unit})")

            if show:
                plt.show()
            # else:
            #     plt.close(fig)

            if close_fig:
                plt.close(fig)

            if save:
                if save_name:
                    fname = save_name
                else:
                    fname = self.path.split("/")[-1]
                    fname = fname.split(".")[-2]
                fig.savefig(fname + "." + save_format, dpi=500)

            return fig

    def importall(FilePath: str, ImportOnly=""):
        """
        Returns a list of Spm objects from a specific folder

        Parameters
        ----------
        FilePath : str
            File path of local directory containing Nanonis files
        FilePrefix : str
            Optional name of file base to be imported e.g. 'img_'
        ImportOnly : 'scan' or 'spec'
            Optional specifier for file type to be imported

        Returns
        -------
        list of Spm objects

        """

        from os import walk

        files = []
        NumSpec = 0
        NumScan = 0
        NumGrid = 0

        for root, dirs, filenames in walk(FilePath):
            for file in filenames:
                if file.endswith(".sxm"):
                    if not ((ImportOnly == "spec") or (ImportOnly == "grid")):
                        files.append(Spm(root + "/" + file))
                        NumScan = NumScan + 1
                elif file.endswith(".dat"):
                    if not ((ImportOnly == "scan") or (ImportOnly == "grid")):
                        files.append(Spm(root + "/" + file))
                        NumSpec = NumSpec + 1
                elif file.endswith(".3ds"):
                    if not ((ImportOnly == "scan") or (ImportOnly == "spec")):
                        files.append(Spm(root + "/" + file))
                        NumGrid = NumGrid + 1

        print(
            str(len(files))
            + " files imported; "
            + str(NumScan)
            + " scan(s), "
            + str(NumSpec)
            + " spectra, and "
            + str(NumGrid)
            + " grids"
        )

        return files
