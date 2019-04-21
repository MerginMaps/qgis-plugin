# User documentation

## Installation
To use Mergin plugin, you will need to:
- Sign up with Mergin service: https://public.cloudmergin.com/
- Install the plugin from QGIS plugin manager

Once, you have installed the plugin, a new provider will appear in your QGIS Browser panel.

<img src="docs/images/mergin-browser.png">

**Note 1**: that there is no menu entry or toolbar icons for Mergin plugin. The only method to interact with the service is through the QGIS Browser panel.

**Note 2**: You may need to restart your QGIS to see Mergin in your QGIS browser panel after the installation.

To be able to view Mergin projects, we need to sign in:

1. In the browser panel, right-click on Mergin
2. Select **Configure**
3. A new window will appear:
  - For **URL**: type **https://public.cloudmergin.com**
  - For **Username**: type your Mergin username
  - For **Password**: type your Mergin password
  - Click **Test Connection** and it should show <span style="color:green">OK</span>.
4. Click **OK**

<img src="docs/images/mergin-settings.png">

To view the list of your projects, click on the arrow to the right of Mergin in your QGIS browser panel.

## Using Mergin plugin
The following functionalities are available from Mergin plugin:

### Create a new project
You can start a new project by right-clicking on Mergin from the browser panel and selecting **Create new project**:

- Type a name for **Project name**
- Selecting **Public** will make your project available to all Mergin users
- **Project Directory** will be the folder where your project and associated layers reside

### Download a project
To download a project:

- Right-click on the project under Mergin, from the browser panel
- Select **Download**
- A new window will appear to set the folder path
- Once the project is downloaded, you can select to Open the downloaded project.

### Synchronise the changes
With Mergin service you can synchronise your local changes back to the server. Simply, right-click on the project from the browser panel and select **Synchronize**

You can also use **Synchronize** function to download changes made to your local projects from Mergin.

### Remove a local/downloaded project
If you no longer want to have the project and its associated files available locally, you can delete them by right-clicking on the project from browser panel and select **Remove locally**.

Ensure to use this function to remove the projects. Deleting the files manually might cause synchronisation problems.
