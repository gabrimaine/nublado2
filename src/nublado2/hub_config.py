# """Configuration definition."""

__all__ = ["HubConfig"]

from jupyterhub.app import JupyterHub
from traitlets.config import LoggingConfigurable

from .hooks import NubladoHooks
from .nublado_config import NubladoConfig


class HubConfig(LoggingConfigurable):
    def configure(self, c: JupyterHub) -> None:
        self.log.info("Configuring JupyterHub Nublado2 style")
        self.log.debug(f"JupyterHub configuration starting as: {c}")

        nc = NubladoConfig().get()
        self.log.debug(f"Nublado Config is:\n{nc}")

        c.JupyterHub.spawner_class = "kubespawner.KubeSpawner"

        # Setup hooks
        hooks = NubladoHooks()
        c.Spawner.pre_spawn_hook = hooks.pre_spawn
        c.Spawner.post_stop_hook = hooks.post_stop
        c.Spawner.options_form = hooks.show_options
        c.Spawner.options_from_form = hooks.get_options

        self.log.info("JupyterHub configuration complete")
        self.log.debug(f"JupyterHub configuration is now: {c}")
