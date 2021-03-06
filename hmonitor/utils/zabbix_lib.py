# -*- coding: utf-8 -*-

import json
import logging

import tornado.httpclient as httpclient
import tornado.httputil as httputil

import hmonitor.common.constants as constants
import hmonitor.utils.cache as cache


class ZabbixProxy(object):

    def __init__(self, username, password, url):
        self.username = username
        self.password = password
        self.url = self._parse_url(url)

    def do_request(self, body):
        body = json.dumps(body)
        http_request = httpclient.HTTPRequest(url=self.url,
                                              method="POST",
                                              headers=httputil.HTTPHeaders(
                                                  {"Content-Type":
                                                       "application/json-rpc"}
                                              ),
                                              body=body)
        http_client = httpclient.HTTPClient()
        logging.debug("SEND REQUEST TO ZABBIX: url: {url}, "
                      "body: {body}".format(
            url=self.url,
            body=body
        ))
        try:
            response = http_client.fetch(http_request)
            result = json.loads(response.body)
        except httpclient.HTTPError as e:
            logging.exception(e)
            result = None
        http_client.close()
        logging.debug("REQUEST RESULT IS: {result}".format(result=result))

        if result and "error" in result:
            logging.error(result["error"])

        return result

    def get_request_id(self):
        return 1

    def get_token(self):
        # TODO(tianhuan) token should be cached here
        method = "user.login"
        request_body = dict(jsonrpc="2.0",
                            method=method,
                            params=dict(user=self.username,
                                        password=self.password),
                            id=self.get_request_id(),
                            auth=None)
        response = self.do_request(request_body)
        return response.get("result", None)

    def get_triggers(self, only_hm=True, db=None):
        if db:
            return db.get_hm_triggers(only_hm)

        method = "trigger.get"
        if cache.get_cached_content(method):
            return cache.get_cached_content(method)

        tmp = dict()

        def _get_trigger_info(k):
            request_body = dict(jsonrpc="2.0",
                                method=method,
                                params=dict(output=[k]),
                                id=self.get_request_id(),
                                auth=self.get_token())
            response = self.do_request(request_body)
            triggers = response.get("result", [])
            for trigger in triggers:
                if trigger["triggerid"] in tmp:
                    tmp[trigger["triggerid"]][k] = trigger[k]
                else:
                    tmp[trigger["triggerid"]] = {k: trigger[k]}

        # I can't get all trigger infos in one request(i don't know why, but
        # Zabbix just give no response to me). So here let's divide request
        # into some small parts
        _get_trigger_info("description")
        _get_trigger_info("comments")
        _get_trigger_info("priority")

        triggers = tmp.values()

        if only_hm is False:
            result = triggers
        else:
            result = [t for t in triggers if
                        t["description"].upper().startswith(
                constants.TRIGGER_PREFIX
            ) and " " not in t["description"]]

        # TODO(tianhuan) Remove duplicated triggers, necessary?
        r = []
        for t in result:
            if t not in r:
                r.append(t)
        r.sort()

        cache.set_cached_content(method, r, 10800)
        return r

    def get_triggers_name(self, only_hm=True, db=None):
        method = "triggers_name"
        if cache.get_cached_content(method):
            return cache.get_cached_content(method)

        triggers = self.get_triggers(only_hm, db)
        triggers_name = []
        for trigger in triggers:
            name = trigger.get("description", None)
            if name and name not in triggers_name:
                triggers_name.append(name.strip())
        triggers_name.sort()
        cache.set_cached_content(method, triggers_name, 1800)
        return triggers_name

    def get_triggers_info(self, only_hm=True, db=None):
        method = "triggers_info"
        if cache.get_cached_content(method):
            return cache.get_cached_content(method)

        triggers = self.get_triggers(only_hm, db)
        triggers_info = {}
        for trigger in triggers:
            name = trigger.get("description", None)
            priority = trigger.get("priority", 0)
            comments = trigger.get("comments", "")
            if name:
                triggers_info[name.strip()] = dict(name=name.strip(),
                                                   priority=priority,
                                                   comments=comments.strip())
        cache.set_cached_content(method, triggers_info, 1800)
        return triggers_info

    def _parse_url(self, url):
        if "http" in url.lower():
            return "{url}/api_jsonrpc.php".format(url=url)
        else:
            return "http://{url}/api_jsonrpc.php".format(url=url)

