# -*- coding: utf-8 -*-
from urllib.parse import parse_qsl


def parse_params(paramstring):
    if not paramstring:
        return {}
    return dict(parse_qsl(paramstring, keep_blank_values=True))
