# AiiDAlab-OpenBIS App

The app contains three different tabs:
- Experiments that contains Sample Preparation and Sample Measurements
- Simulations that contains Import/export simulations from/to openBIS
- AI Agent that contains a page to talk with an openBIS chatbot and a page to setup the LLM model and the Langfuse to track all the interactions

Upload sample measurements:
- Open openbis-drive app
- In the openbis-drive app, click on Synchronization tasks
- Click on + Add to add a new synchronization job
- Fill the personal access token with the user personal access token that you can find out in the openBIS admin interface
- Fill the openBIS server URL with https://openbis-empa-lab205.ethz.ch:443
- In the openBIS entity ID find out the entity ID you want to send the files to.
- Search for the openBIS server directory where you want to send the files to and select it.
- Search for the local directory where the files are located and select it.
- Select Upload as the synchronization mode
- Click on Enabled
- On the Advanced settings: Click on Specific list of ignored files and Copy global default. Then add other types of files you want to ignore. For example, if you want to ignore all the .txt files, add *.txt in the list.
- To start the job click on Apply.
- Open AiiDAlab
- Configure the ELN connection by clicking on the Configure ELN inside aiidalab_widgets_base. There you have to....
- Open AiiDAlab-OpenBIS app
- In the Experiments tab, click on Folder Synchronisation (AFS)...
