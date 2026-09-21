{
    'name': 'FleetFlow',
    'summary': 'Fleet maintenance intake, dispatch, repair and controlled release',
    'version': '16.0.1.0.0',
    'category': 'Services/Fleet',
    'license': 'LGPL-3',
    'depends': ['web', 'fleet', 'mail'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/data.xml',
        'views/views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'fleetflow/static/src/workspace.js',
            'fleetflow/static/src/workspace.xml',
            'fleetflow/static/src/workspace.scss',
        ],
    },
    'application': True,
    'installable': True,
}
