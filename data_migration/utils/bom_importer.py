# -*- coding: utf-8 -*-
##############################################################################
#
# Copyright (c) 2017 Didotech srl (info at didotech.com)
#
#                    All Rights Reserved.
#
# This program is Free Software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

import logging
import math
import sys
import threading
from collections import namedtuple
from datetime import datetime
from pprint import pprint

import codicefiscale
import pooler
from openerp.addons.core_extended.file_manipulation import import_sheet
import vatnumber
from tools.translate import _

import data_migration.settings as settings
from openerp.osv import orm
from utils import Utils

_logger = logging.getLogger(__name__)
_logger.setLevel(logging.DEBUG)

DEBUG = settings.DEBUG

if DEBUG:
    import pdb


class ImportFile(threading.Thread, Utils):
    def __init__(self, cr, uid, ids, context):
        # Inizializzazione superclasse
        threading.Thread.__init__(self)

        # Inizializzazione classe
        self.uid = uid
        self.start_time = datetime.now()
        self.dbname = cr.dbname
        self.pool = pooler.get_pool(cr.dbname)
        self.product_obj = self.pool['product.product']
        self.supplierinfo_obj = self.pool['product.supplierinfo']
        self.bom_obj = self.pool['mrp.bom']

        # Necessario creare un nuovo cursor per il thread, quello fornito dal metodo chiamante viene chiuso
        # alla fine del metodo e diventa inutilizzabile all'interno del thread.
        self.cr = pooler.get_db(self.dbname).cursor()

        self.bomImportID = ids[0]

        self.context = context
        self.error = []
        self.warning = []
        self.first_row = True

        # Contatori dei nuovi prodotti inseriti e dei prodotti aggiornati,
        # vengono utilizzati per compilare il rapporto alla terminazione
        # del processo di import
        self.uo_new = 0
        self.updated = 0
        self.problems = 0
        self.cache = []

    def run(self):
        # Recupera il record dal database
        self.filedata_obj = self.pool['bom.import']
        self.bomImportRecord = self.filedata_obj.browse(self.cr, self.uid, self.bomImportID, context=self.context)
        self.file_name = self.bomImportRecord.file_name.split('\\')[-1]

        self.update_product_name = self.bomImportRecord.update_product_name

        # ===================================================
        Config = getattr(settings, self.bomImportRecord.format)

        self.HEADER = Config.HEADER_BOM
        self.REQUIRED = Config.REQUIRED_BOM
        self.BOM_SEARCH = Config.BOM_SEARCH
        self.BOM_WARNINGS = Config.BOM_WARNINGS
        self.BOM_ERRORS = Config.BOM_ERRORS

        # Default values
        self.BOM_DEFAULTS = Config.BOM_DEFAULTS

        if not len(self.HEADER) == len(Config.COLUMNS_BOM.split(',')):
            pprint(zip(self.HEADER, Config.COLUMNS_BOM.split(',')))
            raise orm.except_orm('Error: wrong configuration!', 'The length of columns and headers must be the same')

        self.RecordBom = namedtuple('RecordBom', Config.COLUMNS_BOM)

        # ===================================================
        try:
            table, self.numberOfLines = import_sheet(self.file_name, self.bomImportRecord.content_text)
        except Exception as e:
            # Annulla le modifiche fatte
            self.cr.rollback()
            self.cr.commit()

            title = "Import failed"
            message = "Errore nell'importazione del file %s" % self.file_name + "\nDettaglio:\n\n" + str(e)

            if DEBUG:
                ### Debug
                _logger.debug(message)
                pdb.set_trace()
            self.notify_import_result(self.cr, self.uid, title, message, error=True, record=self.bomImportRecord)

        if DEBUG:
            # Importa il listino
            self.process(self.cr, self.uid, table)

            # Genera il report sull'importazione
            self.notify_import_result(self.cr, self.uid, self.message_title, 'Importazione completata', record=self.bomImportRecord)
        else:
            # Elaborazione del listino prezzi
            try:
                # Importa il listino
                self.process(self.cr, self.uid, table)

                # Genera il report sull'importazione
                self.notify_import_result(self.cr, self.uid, self.message_title, 'Importazione completata', record=self.bomImportRecord)
            except Exception as e:
                # Annulla le modifiche fatte
                self.cr.rollback()
                self.cr.commit()

                title = "Import failed"
                message = "Errore alla linea %s" % str(self.processed_lines) + "\nDettaglio:\n\n" + str(e)

                if DEBUG:
                    ### Debug
                    _logger.debug(message)
                    pdb.set_trace()

                self.notify_import_result(self.cr, self.uid, title, message, error=True, record=self.bomImportRecord)

    def import_row(self, cr, uid, row_list):
        if self.first_row:
            row_str_list = [self.toStr(value) for value in row_list]

            for column in row_str_list:
                # print column
                if column in self.HEADER:
                    _logger.info('Riga {0}: Trovato Header'.format(self.processed_lines))
                    return True
            self.first_row = False
        if not len(row_list) == len(self.HEADER):
            row_str_list = [self.toStr(value) for value in row_list]
            if DEBUG:
                if len(row_list) > len(self.HEADER):
                    pprint(zip(self.HEADER, row_str_list[:len(self.HEADER)]))
                else:
                    pprint(zip(self.HEADER[:len(row_list)], row_str_list))

            error = u"""Row {row}: Row_list is {row_len} long. We expect it to be {expected} long, with this columns:
                {keys}
                Instead of this we got this:
                {header}
                """.format(row=self.processed_lines, row_len=len(row_list), expected=len(self.HEADER), keys=self.HEADER, header=', '.join(map(lambda s: s or '', row_str_list)))

            _logger.error(str(row_list))
            _logger.error(error)
            self.error.append(error)
            return False
        elif DEBUG:
            # pprint(row_list)
            row_str_list = [self.toStr(value) for value in row_list]
            pprint(zip(self.HEADER, row_str_list))

        # Sometime value is only numeric and we don't want string to be treated as Float
        record = self.RecordBom._make([self.toStr(value) for value in row_list])
        print record
        # if record.default_code and record.default_code in self.cache:
        #     _logger.warning(u'Code {0} already processed'.format(record.default_code))
        #     # return False
        # elif record.default_code:
        #     self.cache.append(record.default_code)

        for field in self.REQUIRED:
            if not getattr(record, field):
                error = "Riga {0}: Manca il valore della {1}. La riga viene ignorata.".format(self.processed_lines, field)
                _logger.debug(error)
                self.error.append(error)
                return False

        product_vals_bom = self.bom_obj.default_get(cr, uid, ['product_qty', 'type', 'company_id', 'sequence', 'product_rounding', 'active', 'product_efficiency'], self.context)
        # res = super(ImportFile, self).onchange_product_id(cr, uid, ids, product_id, name, context=context)

        # for field in self.BOM_SEARCH:
        #     if hasattr(record, field) and getattr(record, field):
        #         product_vals_bom[field] = getattr(record, field)
        #         break
        # else:
        #     error = "Row {0}: Can't find valid product key".format(self.processed_lines)
        #     _logger.error(error)
        #     self.error.append(error)
        #     return False

        product_ids = self.product_obj.search(cr, uid, [('default_code', '=', record.default_code)], context=self.context)
        if product_ids:
            product = self.product_obj.browse(cr, uid, product_ids[0], context=self.context)
            product_onchange = self.bom_obj.onchange_product_id(cr, uid, self.bomImportID, product.id, product.name, context=self.context).get('value')
            product_vals_bom.update({
                'product_id': product.id,
                'name': product_onchange['name'],
                'product_uom': product_onchange['product_uom']
            })

            sub_item_ids = self.product_obj.search(cr, uid, [('default_code', '=', record.sub_item)], context=self.context)
            if sub_item_ids:
                bom_lines = self.bom_obj.default_get(cr, uid, ['product_qty', 'type', 'company_id', 'sequence', 'product_rounding', 'active', 'product_efficiency'], self.context)
                sub_item = self.product_obj.browse(cr, uid, sub_item_ids[0], context=self.context)
                sub_item_onchange = self.bom_obj.onchange_product_id(cr, uid, self.bomImportID, sub_item.id, sub_item.name, context=self.context).get('value')
                bom_lines.update({
                    'product_id': sub_item.id,
                    'name': sub_item_onchange['name'],
                    'product_uom': sub_item_onchange['product_uom']
                })

                if hasattr(record, 'product_qty') and record.product_qty:
                    bom_lines['product_qty'] = record.product_qty

                if hasattr(record, 'position') and record.position:
                    bom_lines['position'] = record.position

                product_bom_ids = self.bom_obj.search(cr, uid, [('product_id', '=', product.id), ('bom_id', '=', None)], context=self.context)
                if product_bom_ids:
                    product_bom_id = product_bom_ids[0]
                    self.bom_obj.write(cr, uid, product_bom_id, product_vals_bom, self.context)

                    sub_item_bom_ids = self.bom_obj.search(cr, uid, [('product_id', '=', sub_item.id), ('bom_id', '=', product_bom_id)], context=self.context)
                    bom_lines.update({'bom_id': product_bom_id})
                    if sub_item_bom_ids:
                        sub_item_bom_id = sub_item_bom_ids[0]
                        self.bom_obj.write(cr, uid, sub_item_bom_id, bom_lines, self.context)
                    else:
                        sub_item_bom_id = self.bom_obj.create(cr, uid, bom_lines, self.context)
                else:
                    product_bom_id = self.bom_obj.create(cr, uid, product_vals_bom, self.context)
                    bom_lines.update({'bom_id': product_bom_id})
                    sub_item_bom_id = self.bom_obj.create(cr, uid, bom_lines, self.context)
            else:
                error = 'Prodotto: {code} non presente nel DB.'.format(code=record.sub_item)
                if error not in self.error:
                    _logger.debug(error)
                    self.error.append(error)
                return False
        else:
            error = 'Prodotto: {code} non presente nel DB.'.format(code=record.default_code)
            if error not in self.error:
                _logger.debug(error)
                self.error.append(error)
            return False

    def process(self, cr, uid, table):
        self.message_title = _("Importazione Distinta Base")
        self.progressIndicator = 0

        notifyProgressStep = (self.numberOfLines / 100) + 1  # NB: divisione tra interi da sempre un numero intero!
        # NB: il + 1 alla fine serve ad evitare divisioni per zero

        # Use counter of processed lines
        # If this line generate an error we will know the right Line Number
        for self.processed_lines, row_list in enumerate(table, start=1):
            if not self.import_row(cr, uid, row_list):
                self.problems += 1

            if (self.processed_lines % notifyProgressStep) == 0:
                cr.commit()
                completedQuota = float(self.processed_lines) / float(self.numberOfLines)
                completedPercentage = math.trunc(completedQuota * 100)
                self.progressIndicator = completedPercentage
                self.updateProgressIndicator(cr, uid, self.bomImportID)

        self.progressIndicator = 100
        self.updateProgressIndicator(cr, uid, self.bomImportID)

        return True
