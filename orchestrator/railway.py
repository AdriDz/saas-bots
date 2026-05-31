"""
Automatización de Railway vía API GraphQL.

Permite crear un proyecto nuevo, desplegar el bot de la plantilla desde GitHub,
inyectar las variables de entorno y pausar/reanudar el servicio.

Reutiliza la misma API que ya usamos a mano con los bots existentes.
"""
import aiohttp

from . import config


async def _gql(query: str, variables: dict | None = None) -> dict:
    """Ejecuta una query/mutation contra la API de Railway."""
    headers = {
        "Authorization": f"Bearer {config.RAILWAY_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {"query": query, "variables": variables or {}}
    async with aiohttp.ClientSession() as session:
        async with session.post(config.RAILWAY_GQL, json=payload, headers=headers, timeout=60) as resp:
            data = await resp.json()
            if "errors" in data:
                raise RuntimeError(f"Railway API error: {data['errors']}")
            return data["data"]


async def create_project(name: str) -> str:
    """Crea un proyecto nuevo y devuelve su id."""
    query = """
    mutation projectCreate($input: ProjectCreateInput!) {
      projectCreate(input: $input) { id }
    }
    """
    data = await _gql(query, {"input": {"name": name}})
    return data["projectCreate"]["id"]


async def get_environment(project_id: str) -> str:
    """Devuelve el id del entorno 'production' del proyecto."""
    query = """
    query project($id: String!) {
      project(id: $id) {
        environments { edges { node { id name } } }
      }
    }
    """
    data = await _gql(query, {"id": project_id})
    edges = data["project"]["environments"]["edges"]
    for e in edges:
        if e["node"]["name"] == "production":
            return e["node"]["id"]
    return edges[0]["node"]["id"]


async def create_service_from_repo(project_id: str, repo: str, name: str) -> str:
    """Crea un servicio que despliega desde un repo de GitHub. Devuelve service_id."""
    query = """
    mutation serviceCreate($input: ServiceCreateInput!) {
      serviceCreate(input: $input) { id }
    }
    """
    variables = {"input": {
        "projectId": project_id,
        "name": name,
        "source": {"repo": repo},
    }}
    data = await _gql(query, variables)
    return data["serviceCreate"]["id"]


async def set_variable(project_id: str, env_id: str, service_id: str, name: str, value: str):
    """Inyecta una variable de entorno en el servicio."""
    query = """
    mutation variableUpsert($input: VariableUpsertInput!) {
      variableUpsert(input: $input)
    }
    """
    variables = {"input": {
        "projectId": project_id,
        "environmentId": env_id,
        "serviceId": service_id,
        "name": name,
        "value": value,
    }}
    await _gql(query, variables)


async def set_variables(project_id: str, env_id: str, service_id: str, variables: dict[str, str]):
    """
    Inyecta TODAS las variables en UNA sola llamada (variableCollectionUpsert).

    Importante: hacerlo de una vez provoca UN único redeploy. Si se metieran una a
    una, Railway redesplegaría por cada variable, y al ser un bot con polling se
    pisarían varias instancias a la vez (error 'Conflict: terminated by other
    getUpdates request').
    """
    query = """
    mutation variableCollectionUpsert($input: VariableCollectionUpsertInput!) {
      variableCollectionUpsert(input: $input)
    }
    """
    payload = {"input": {
        "projectId": project_id,
        "environmentId": env_id,
        "serviceId": service_id,
        "variables": {k: str(v) for k, v in variables.items()},
    }}
    await _gql(query, payload)


async def deploy(service_id: str, env_id: str) -> bool:
    """Lanza un redeploy del servicio."""
    query = """
    mutation serviceInstanceRedeploy($serviceId: String!, $environmentId: String!) {
      serviceInstanceRedeploy(serviceId: $serviceId, environmentId: $environmentId)
    }
    """
    await _gql(query, {"serviceId": service_id, "environmentId": env_id})
    return True


async def pause(service_id: str, env_id: str) -> bool:
    """Pausa el servicio (cuando el cliente deja de pagar)."""
    query = """
    mutation serviceInstanceUpdate($serviceId: String!, $environmentId: String!, $input: ServiceInstanceUpdateInput!) {
      serviceInstanceUpdate(serviceId: $serviceId, environmentId: $environmentId, input: $input)
    }
    """
    # numReplicas = 0 apaga el servicio sin borrarlo
    await _gql(query, {
        "serviceId": service_id,
        "environmentId": env_id,
        "input": {"numReplicas": 0},
    })
    return True


async def resume(service_id: str, env_id: str) -> bool:
    """Reanuda el servicio (cuando vuelve a pagar)."""
    query = """
    mutation serviceInstanceUpdate($serviceId: String!, $environmentId: String!, $input: ServiceInstanceUpdateInput!) {
      serviceInstanceUpdate(serviceId: $serviceId, environmentId: $environmentId, input: $input)
    }
    """
    await _gql(query, {
        "serviceId": service_id,
        "environmentId": env_id,
        "input": {"numReplicas": 1},
    })
    await deploy(service_id, env_id)
    return True
