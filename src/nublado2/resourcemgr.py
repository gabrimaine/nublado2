from jinja2 import Template
from jupyterhub.spawner import Spawner
from kubernetes import client, config
from kubernetes.utils import create_from_dict
from ruamel import yaml
from ruamel.yaml import RoundTripDumper, RoundTripLoader
from traitlets.config import LoggingConfigurable

from nublado2.nublado_config import NubladoConfig

config.load_incluster_config()


class ResourceManager(LoggingConfigurable):
    # These k8s clients don't copy well with locks, connection,
    # pools, locks, etc.  Copying seems to happen under the hood of the
    # LoggingConfigurable base class, so just have them be class variables.
    # Should be safe to share these, and better to have fewer of them.
    k8s_api = client.api_client.ApiClient()
    k8s_client = client.CoreV1Api()

    async def create_user_resources(self, spawner: Spawner) -> None:
        """Create the user resources for this spawning session."""
        try:
            auth_state = await spawner.user.get_auth_state()
            self.log.debug(f"Auth state={auth_state}")

            groups = auth_state["groups"]

            # Build a comma separated list of group:gid
            # ex: group1:1000,group2:1001,group3:1002
            external_groups = ",".join(
                [f'{g["name"]}:{g["id"]}' for g in groups]
            )

            template_values = {
                "user_namespace": spawner.namespace,
                "user": spawner.user.name,
                "uid": auth_state["uid"],
                "token": auth_state["token"],
                "groups": groups,
                "external_groups": external_groups,
                "base_url": NubladoConfig().get().get("base_url"),
                "dask_yaml": await self._build_dask_template(spawner),
            }

            self.log.debug(f"Template values={template_values}")
            resources = NubladoConfig().get().get("user_resources", [])
            for r in resources:
                t_yaml = yaml.dump(r, Dumper=RoundTripDumper)
                self.log.debug(f"Resource template:\n{t_yaml}")
                t = Template(t_yaml)
                templated_yaml = t.render(template_values)
                self.log.debug(f"Creating resource:\n{templated_yaml}")
                templated_resource = yaml.load(
                    templated_yaml, Loader=RoundTripLoader
                )
                create_from_dict(self.k8s_api, templated_resource)
        except Exception:
            self.log.exception("Exception creating user resource!")
            raise

    async def _build_dask_template(self, spawner: Spawner) -> str:
        """Build a template for dask workers from the jupyter pod manifest."""
        dask_template = await spawner.get_pod_manifest()

        # Here we make a few mangles to the jupyter pod manifest
        # before using it for templating.  This will end up
        # being used for the pod template for dask.
        # Unset the name of the container, to let dask make the container
        # names, otherwise you'll get an obtuse error from k8s about not
        # being able to create the container.
        dask_template.metadata.name = None

        # This is an argument to the provisioning script to signal it
        # as a dask worker.
        dask_template.spec.containers[0].env.append(
            client.models.V1EnvVar(name="DASK_WORKER", value="TRUE")
        )

        # This will take the python model names and transform
        # them to the names kubernetes expects, which to_dict
        # alone doesn't.
        dask_yaml = yaml.dump(
            self.k8s_api.sanitize_for_serialization(dask_template)
        )

        if not dask_yaml:
            # This is mostly to help with the typing.
            raise Exception("Dask template ended up empty.")
        else:
            return dask_yaml

    def delete_user_resources(self, namespace: str) -> None:
        """Clean up a jupyterlab by deleting the whole namespace.

        The reason is it's easier to do this than try to make a list
        of resources to delete, especially when new things may be
        dynamically created outside of the hub, like dask."""
        self.k8s_client.delete_namespace(name=namespace)