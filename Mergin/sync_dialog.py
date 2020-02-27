import os
from qgis.PyQt.QtWidgets import QDialog, QDialogButtonBox, QFileDialog, QApplication, QMessageBox
from qgis.PyQt import uic
from qgis.PyQt.QtCore import QSettings, Qt, QTimer

from qgis.core import QgsApplication

from .utils import ClientError, LoginError
from urllib.error import URLError


from .utils import download_project_async, download_project_is_running, \
                                    download_project_finalize, download_project_cancel

ui_file = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'ui', 'ui_sync_dialog.ui')


class SyncDialog(QDialog):

    # possible operations
    DOWNLOAD = 1   # initial download of a project
    SYNC = 2       # synchronization (pull followed by push)

    def __init__(self, operation, mergin_client, target_dir, project_name):
        QDialog.__init__(self)
        self.ui = uic.loadUi(ui_file, self)

        self.operation = operation
        self.mergin_client = mergin_client
        self.target_dir = target_dir
        self.project_name = project_name

        self.is_complete = False
        self.job = None

        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.timer_timeout)

        self.btnCancel.clicked.connect(self.cancel_download)

    def start_download(self):

        self.labelStatus.setText("Querying project...")

        QApplication.setOverrideCursor(Qt.WaitCursor)

        try:
            self.job = download_project_async(self.mergin_client, self.project_name, self.target_dir)
        except (URLError, ValueError) as e:
            QgsApplication.messageLog().logMessage(f"Mergin plugin: {str(e)}")
            msg = "Failed to download your project {}.\n" \
                  "Please make sure your Mergin settings are correct".format(self.project_name)
            QMessageBox.critical(None, 'Project download', msg, QMessageBox.Close)
        except LoginError as e:
            QgsApplication.messageLog().logMessage(f"Mergin plugin: {str(e)}")
            msg = "<font color=red>Security token has been expired, failed to renew. Check your username and password </font>"
            QMessageBox.critical(None, 'Login failed', msg, QMessageBox.Close)
        except Exception as e:
            msg = "Failed to download your project {}.\n" \
                  "{}".format(self.project_name, str(e))
            QMessageBox.critical(None, 'Project download', msg, QMessageBox.Close)

        QApplication.restoreOverrideCursor()

        if not self.job:
            return   # there was an error

        self.progress.setMaximum(self.job.total_size)
        self.progress.setValue(0)

        self.timer.start()

        self.labelStatus.setText("Downloading project...")

    def timer_timeout(self):

        self.progress.setValue(self.job.transferred_size)

        try:
            is_running = download_project_is_running(self.job)
        except ClientError as e:

            self.timer.stop()

            # also try to cancel the job so that we do not need to wait for other workers
            download_project_cancel(self.job)
            self.job = None

            QMessageBox.critical(self, "Download Project", "Client error: " + str(e))
            self.close()
            return

        if not is_running:
            self.timer.stop()
            try:
                # this should not raise an exception anymore because we were signalled that
                # all workers have finished successfully. But maybe something in finalization could fail (e.g. disk full?)
                download_project_finalize(self.job)
            except ClientError as e:
                self.job = None
                QMessageBox.critical(self, "Download Project", "Client error: " + str(e))
                self.close()
                return

            self.job = None
            self.is_complete = True
            self.close()

    def cancel_download(self):
        assert self.job

        self.timer.stop()

        self.labelStatus.setText("Cancelling download...")

        QApplication.setOverrideCursor(Qt.WaitCursor)

        download_project_cancel(self.job)

        QApplication.restoreOverrideCursor()

        self.job = None
        self.close()