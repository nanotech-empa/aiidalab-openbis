function CustomToolbarPluginViewTechnology() {
    this.init();
}

function fetchOptionsToDepth(depth, initialOptions){
    if (depth <= 0) {
      // Base case: Stop recursion and return an empty fetch options
      return initialOptions;
    }

    const fo = initialOptions;
    fo.withParentsUsing(fetchOptionsToDepth(depth - 1, initialOptions));
    return fo;
}

function getObjectPropertiesJson(sample){
    var jsonObj = {
        "name": sample.properties['$NAME'],
        "smiles":sample.properties['SMILES'],
        "@context": {
            "schema": "http://schema.org/",
            "name": "schema:name",
            "smiles": "schema:smiles",
            "Molecule": "schema:MolecularEntity"
        }
    };
    return jsonObj;
}

function getWFMSConnectionURL(experiment, sample, dataType){
    var samplePropsJson = getObjectPropertiesJson(sample);
    var wfmsURL = "http://localhost:8888/apps/apps/aiidalab-widgets-base/notebooks/eln_import.ipynb";
    var elnInstance = "https://local.openbis.ch";
    var dataType = dataType;
    var elnType = "openbis";
    var moleculeUUID = sample.permId;
    var jsonStr = JSON.stringify(samplePropsJson);
    var encodedJsonStr = encodeURIComponent(jsonStr);
    if (experiment == ""){
        var expUUID = "";
    }
    else{
        var expUUID = experiment.permId;
    }
    var src = `${wfmsURL}?eln_instance=${elnInstance}&data_type=${dataType}&eln_type=${elnType}&sample_uuid=${moleculeUUID}&molecule_uuid=${moleculeUUID}&molecule_info=${encodedJsonStr}&appmode_scroll=249.5`;
    return src
}

$.extend(CustomToolbarPluginViewTechnology.prototype, ELNLIMSPlugin.prototype, {

    init: function() {

    },

    experimentTypeDefinitionsExtension : {
        "EXPERIMENT" : {
            extraToolbar : function(mode, experiment) {
                var toolbarModel = [];
                if(mode === FormMode.VIEW) {

                    var $demoButton = FormUtil.getButtonWithIcon("fa fa-info-circle", function() {
                        console.log("Loading...")
                    }, "AiiDALab");

                    // Add the button to the toolbar model immediately
                    toolbarModel.push({ component: $demoButton, tooltip: "AiiDALab" });

                    require(["openbis", "as/dto/sample/search/SampleSearchCriteria", "as/dto/sample/fetchoptions/SampleFetchOptions" ], function(openbis, SampleSearchCriteria, SampleFetchOptions) {

                        $demoButton.off("click").on("click", function() {

                            var v3 = new openbis();

                            v3.login("admin", "123456789").done(function() {
                                var criteria = new SampleSearchCriteria();
                                criteria.withExperiment().withIdentifier().thatEquals(experiment.identifier);
                                criteria.withType().withCode().thatEquals("DEPOSITION");

                                // tell the API to fetch properties for each returned sample
                                var fetchOptions = fetchOptionsToDepth(1, new SampleFetchOptions());
                                fetchOptions.withProperties();

                                v3.searchSamples(criteria, fetchOptions).done(function(result) {
                                    result.getObjects().forEach(function(sample) {
                                        sample.getParents().forEach(function(parent) {
                                            if(parent.getCode().startsWith("SUBST")){
                                                var substMolecule = parent.getProperty("HAS_MOLECULE")

                                                var secondCriteria = new SampleSearchCriteria();
                                                secondCriteria.withType().withCode().thatEquals("MOLECULE");
                                                var fetchOptions = fetchOptionsToDepth(0, new SampleFetchOptions());
                                                fetchOptions.withProperties()

                                                v3.searchSamples(secondCriteria, fetchOptions).done(function(result) {
                                                    result.getObjects().forEach(function(sample) {
                                                        if(sample.getPermId() == substMolecule){
                                                            var src = getWFMSConnectionURL(experiment, sample);
                                                            var win = window.open(src, '_blank');
                                                            win.focus();
                                                        }
                                                    });
                                                });
                                            }
                                        });
                                    });
                                });
                            });

                            v3.logout();
                        });
                    });
                }
                return toolbarModel;
            }
        },
    },

    sampleTypeDefinitionsExtension : {
        "MOLECULE" : {
            extraToolbar : function(mode, sample) {
                var toolbarModel = [];
                if(mode === FormMode.VIEW) {
                    var $demoButton = FormUtil.getButtonWithIcon("fa fa-info-circle", function () {
                        var src = getWFMSConnectionURL("", sample, "MOLECULE");
                        var win = window.open(src, '_blank');
                        win.focus();

                    }, "AiiDALab");
                    toolbarModel.push({component : $demoButton, tooltip: "AiiDALab"});
                }
                return toolbarModel;
            }
        },
    }
});

profile.plugins.push(new CustomToolbarPluginViewTechnology());
