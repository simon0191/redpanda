#!/usr/bin/env python3
import sys
import os
import logging
import json

# 3rd party
from jinja2 import Template
import zlib

sys.path.append(os.path.dirname(__file__))
logger = logging.getLogger('rp')

# internal
import log

RPC_TEMPLATE = """
// This file is autogenerated. Manual changes will be lost.
#pragma once

#include "rpc/types.h"
#include "rpc/netbuf.h"
#include "rpc/parse_utils.h"
#include "rpc/transport.h"
#include "rpc/service.h"
#include "finjector/hbadger.h"
#include "utils/string_switch.h"
#include "random/fast_prng.h"
#include "seastarx.h"

// extra includes
{%- for include in includes %}
#include "{{include}}"
{%- endfor %}

#include <seastar/core/reactor.hh>
#include <seastar/core/sleep.hh>
#include <seastar/core/scheduling.hh>

#include <functional>
#include <chrono>
#include <tuple>
#include <cstdint>

namespace {{namespace}} {

class {{service_name}}_service : public rpc::service {
public:
    class failure_probes;

    {{service_name}}_service(scheduling_group sc, smp_service_group ssg)
       : _sc(sc), _ssg(ssg) {}

    {{service_name}}_service({{service_name}}_service&& o) noexcept
      : _sc(std::move(o._sc)), _ssg(std::move(o._ssg)), _methods(std::move(o._methods)) {}

    {{service_name}}_service& operator=({{service_name}}_service&& o) noexcept {
       if(this != &o){
          this->~{{service_name}}_service();
          new (this) {{service_name}}_service(std::move(o));
       }
       return *this;
    }

    virtual ~{{service_name}}_service() noexcept = default;

    scheduling_group& get_scheduling_group() override {
       return _sc;
    }

    smp_service_group& get_smp_service_group() override {
       return _ssg;
    }

    rpc::method* method_from_id(uint32_t idx) final {
       switch(idx) {
       {%- for method in methods %}
         case {{method.id}}: return &_methods[{{loop.index - 1}}];
       {%- endfor %}
         default: return nullptr;
       }
    }
    {%- for method in methods %}
    /// \\brief {{method.input_type}} -> {{method.output_type}}
    virtual future<rpc::netbuf>
    raw_{{method.name}}(input_stream<char>& in, rpc::streaming_context& ctx) {
      auto fapply = execution_helper<{{method.input_type}}, {{method.output_type}}>();
      return fapply.exec(in, ctx, {{method.id}}, [this](
          {{method.input_type}}&& t, rpc::streaming_context& ctx) -> future<{{method.output_type}}> {
          return {{method.name}}(std::move(t), ctx);
      });
    }
    virtual future<{{method.output_type}}>
    {{method.name}}({{method.input_type}}&&, rpc::streaming_context&) {
       throw std::runtime_error("unimplemented method");
    }
    {%- endfor %}
private:
    scheduling_group _sc;
    smp_service_group _ssg;
    std::array<rpc::method, {{methods|length}}> _methods{%raw %}{{{% endraw %}
      {%- for method in methods %}
      rpc::method([this] (input_stream<char>& in, rpc::streaming_context& ctx) {
         return raw_{{method.name}}(in, ctx);
      }){{ "," if not loop.last }}
      {%- endfor %}
    {% raw %}}}{% endraw %};
};
class {{service_name}}_client_protocol {
public:
    explicit {{service_name}}_client_protocol(rpc::transport& t)
      : _transport(t) {
    }
    {%- for method in methods %}
    virtual inline future<rpc::client_context<{{method.output_type}}>>
    {{method.name}}({{method.input_type}}&& r) {
       return _transport.send_typed<{{method.input_type}}, {{method.output_type}}>(std::move(r), {{method.id}});
    }
    {%- endfor %}

private:
    rpc::transport& _transport;
};

class {{service_name}}_service::failure_probes final : public finjector::probe {
public:
    using type = int8_t;

    static constexpr std::string_view name() { return "{{service_name}}_service::failure_probes"; }

    enum class methods: type {
    {%- for method in methods %}
        {{method.name}} = 1 << {{loop.index}}{{ "," if not loop.last }}
    {%- endfor %}
    };
    type method_for_point(std::string_view point) const final {
        return string_switch<type>(point)
        {%- for method in methods %}
          .match("{{method.name}}", static_cast<type>(methods::{{method.name}}))
        {%- endfor %}
          .default_match(0);
    }
    std::vector<sstring> points() final {
        std::vector<sstring> retval;
        retval.reserve({{methods | length}});
        {%- for method in methods %}
        retval.push_back("{{method.name}}");
        {%- endfor %}
        return retval;
    }
    {%- for method in methods %}
    future<> {{method.name}}() {
        if(is_enabled()) {
          return do_{{method.name}}();
        }
        return make_ready_future<>();
    }
    {%- endfor %}
private:
    {%- for method in methods %}
    [[gnu::noinline]] future<> do_{{method.name}}() {
        if (_exception_methods & type(methods::{{method.name}})) {
          return make_exception_future<>(std::runtime_error(
            "FailureInjector: "
            "{{namespace}}::{{service_name}}::{{method.name}}"));
        }
        if (_delay_methods & type(methods::{{method.name}})) {
            return sleep(std::chrono::milliseconds(_prng() % 50));
        }
        if (_termination_methods & type(methods::{{method.name}})) {
            std::terminate();
        }
        return make_ready_future<>();
    }
    {%- endfor %}

    fast_prng _prng;
};

} // namespace
"""


def _read_file(name):
    with open(name, 'r') as f:
        return json.load(f)


def _enrich_methods(service):
    logger.info(service)

    service["id"] = zlib.crc32(
        bytes("%s:%s" % (service["namespace"], service["service_name"]),
              "utf-8"))

    def _xor_id(m):
        mid = ("%s:" % service["namespace"]).join(
            [m["name"], m["input_type"], m["output_type"]])
        return service["id"] ^ zlib.crc32(bytes(mid, 'utf-8'))

    for m in service["methods"]:
        m["id"] = _xor_id(m)

    return service


def _codegen(service, out):
    logger.info(service)
    tpl = Template(RPC_TEMPLATE)
    with open(out, 'w') as f:
        f.write(tpl.render(service))


def main():
    import argparse

    def generate_options():
        parser = argparse.ArgumentParser(description='service codegenerator')
        parser.add_argument(
            '--log',
            type=str,
            default='INFO',
            help='info,debug, type log levels. i.e: --log=debug')
        parser.add_argument('--service_file',
                            type=str,
                            help='input file in .json format for the codegen')
        parser.add_argument('--output_file',
                            type=str,
                            default='/dev/stderr',
                            help='output header file for the codegen')
        return parser

    parser = generate_options()
    options, program_options = parser.parse_known_args()
    log.set_logger_for_main(getattr(logging, options.log.upper()))
    logger.info("%s" % options)
    _codegen(_enrich_methods(_read_file(options.service_file)),
             options.output_file)


if __name__ == '__main__':
    main()
