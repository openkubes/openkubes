"""The cluster-scoped EnvironmentConfig the Composition reads its profile and settings from."""

def profile_config(profile, provider_config, pull_secret=''):
    data = {'profile': profile, 'providerConfigName': provider_config}
    if pull_secret: data['imagePullSecret'] = pull_secret
    return {'apiVersion': 'apiextensions.crossplane.io/v1beta1', 'kind': 'EnvironmentConfig',
            'metadata': {'name': 'developer-workspace-profile'}, 'data': data}
