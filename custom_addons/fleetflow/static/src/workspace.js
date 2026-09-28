/** @odoo-module **/

import { registry } from '@web/core/registry';
import { useService } from '@web/core/utils/hooks';
import { deserializeDateTime, formatDateTime } from '@web/core/l10n/dates';
import { _t } from '@web/core/l10n/translation';

const { Component, onWillStart, useState } = owl;

export class FleetFlowWorkspace extends Component {
    setup() {
        this.orm = useService('orm');
        this.action = useService('action');
        this.state = useState({ loading: true, error: false, data: null });
        this.stageLabels = {
            intake: _t('Intake'), approved: _t('Scheduled'),
            in_progress: _t('In progress'), quality: _t('Release review'),
        };
        onWillStart(() => this.load());
    }

    async load() {
        if (this._requestPending) return;
        this._requestPending = true;
        this.state.loading = true;
        this.state.error = false;
        try {
            this.state.data = await this.orm.call('fleetflow.order', 'get_workspace_data', []);
        } catch (error) {
            this.state.error = true;
        } finally {
            this.state.loading = false;
            this._requestPending = false;
        }
    }

    openAction(xmlid) {
        return this.action.doAction(xmlid);
    }

    openOrders(filter = 'open') {
        // Use server-computed cutoffs (reference_time / released_since) so the
        // drill-through matches the server-side metric counts. Never derive the
        // cutoff from the browser clock, which can be skewed.
        const data = this.state.data || {};
        let domain = [['stage', 'not in', ['done', 'cancelled']]];
        if (filter === 'overdue') {
            domain.push(['due_at', '<', data.reference_time]);
        } else if (filter === 'released') {
            domain = [['stage', '=', 'done'], ['released_at', '>=', data.released_since]];
        } else if (filter !== 'open') {
            domain = [['stage', '=', filter]];
        }
        return this.action.doAction({
            type: 'ir.actions.act_window', name: _t('Work orders'),
            res_model: 'fleetflow.order', domain,
            views: [[false, 'kanban'], [false, 'tree'], [false, 'form']],
            context: {},
        });
    }

    newOrder() {
        return this.action.doAction({
            type: 'ir.actions.act_window', name: _t('New work order'),
            res_model: 'fleetflow.order', views: [[false, 'form']], target: 'current',
        });
    }

    openOrder(id) {
        return this.action.doAction({
            type: 'ir.actions.act_window', name: _t('Work order'),
            res_model: 'fleetflow.order', res_id: id, views: [[false, 'form']],
        });
    }

    deadline(value) {
        return value ? formatDateTime(deserializeDateTime(value)) : _t('Not set');
    }

    stageWidth(count) {
        return `${Math.round(100 * count / Math.max(this.state.data.open, 1))}%`;
    }
}

FleetFlowWorkspace.template = 'fleetflow.Workspace';
registry.category('actions').add('fleetflow.workspace', FleetFlowWorkspace);
